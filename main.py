"""DCEMI render EMI recipes as images, in discord.

Three slash commands, mirroring the DCEMI socket protocol:
  - `/recipe <item>` - the friendly one: autocompletes the item id, then pages
    through every recipe for that item with ◀ ▶ buttons (uses /list + /recipe +
    /render under the hood).
  - `/list <query>`  - search EMI's item index by substring.
  - `/render <recipe_id>` - render one recipe by its raw id.

Connect-only: it talks to a running DCEMI renderer over TCP (DCEMI_HOST/
DCEMI_PORT, default 127.0.0.1:25599).
"""

import io

import discord
from discord import app_commands
from discord.ext import commands

from api import commands as apicommands
from api import gui
from . import client


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DCEMI(bot))


async def _open_recipes(interaction: discord.Interaction, item: str) -> None:
    try:
        ids = await client.recipes(item)
    except client.DcemiError as e:
        await interaction.followup.send(f":warning: {e}")
        return
    if isinstance(ids, dict) or not ids:
        await interaction.followup.send(f"No recipes found for `{item}`.")
        return
    view = RecipeView(item, ids)
    embed, file = await view.render()
    if file is None:
        await interaction.followup.send(":warning: Failed to render recipe.")
        return
    await interaction.followup.send(embed=embed, file=file, view=view)


def _recipe_card(title: str, rid: str, png: bytes, index: int = 0, total: int = 1):
    file = discord.File(io.BytesIO(png), filename="recipe.png")
    embed = discord.Embed(title=title, description=f"`{rid}`")
    if total > 1:
        embed.set_footer(text=f"Recipe {index + 1}/{total}")
    embed.set_image(url="attachment://recipe.png")
    return embed, file


class DCEMI(apicommands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="recipe", description="Render a Minecraft recipe from EMI")
    @app_commands.describe(item="Item id, e.g. minecraft:iron_sword")
    async def recipe(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        await _open_recipes(interaction, item)

    @recipe.autocomplete("item")
    async def item_autocomplete(self, interaction: discord.Interaction, current: str):
        if not current:
            return []
        try:
            items = await client.search(current)
        except client.DcemiError:
            return []
        return [app_commands.Choice(name=i, value=i) for i in items[:25]]

    @app_commands.command(name="list", description="Search EMI's item index by substring")
    @app_commands.describe(query="Text to match against item ids, e.g. iron")
    async def list_items(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        try:
            items = await client.search(query)
        except client.DcemiError as e:
            return await interaction.followup.send(f":warning: {e}")

        if not items:
            return await interaction.followup.send(f"No items match `{query}`.")

        view = ItemListUI({"query": query, "items": items})
        await interaction.followup.send(embed=view.embed, view=view)
        return None

    @app_commands.command(name="render", description="Render one recipe by its id (from /recipe) to an image")
    @app_commands.describe(recipe_id="Recipe id, e.g. minecraft:iron_sword or emi:/anvil/...")
    async def render_recipe(self, interaction: discord.Interaction, recipe_id: str):
        await interaction.response.defer()
        try:
            png = await client.render(recipe_id)
        except client.DcemiError as e:
            return await interaction.followup.send(f":warning: {e}")

        if png is None:
            return await interaction.followup.send(
                f":warning: Could not render `{recipe_id}` (unknown recipe id or render error).")

        embed, file = _recipe_card(recipe_id, recipe_id, png)
        await interaction.followup.send(embed=embed, file=file)
        return None


class ItemListUI(gui.PageUI):
    ROW = 3
    PER_PAGE = (ROW - 1) * 5

    def __init__(self, data_transfer=None, page: int = 1):
        data = data_transfer or {"query": "", "items": []}
        items = data["items"]
        embed = discord.Embed(
            title=f"Items matching “{data['query']}”",
            description=f"{len(items)} match(es) — click an item to see its recipes.",
        )
        super().__init__(
            element_count=len(items),
            data_transfer=data,
            embed=embed,
            page=page,
            row=self.ROW,
        )
        self._add_item_buttons(items, page)

    def _add_item_buttons(self, items, page):
        start = (page - 1) * self.PER_PAGE
        for offset, item in enumerate(items[start:start + self.PER_PAGE]):
            button = discord.ui.Button(
                label=item[:80],
                custom_id=f"dcemi_item_{start + offset}",
                row=offset // 5,
            )
            button.callback = self._open(item)
            self.add_item(button)

    @staticmethod
    def _open(item: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await _open_recipes(interaction, item)

        return callback


class RecipeView(discord.ui.View):
    def __init__(self, item: str, ids: list[str]):
        super().__init__(timeout=300)
        self.item = item
        self.ids = ids
        self.index = 0

    async def render(self):
        rid = self.ids[self.index]
        try:
            png = await client.render(rid)
        except client.DcemiError:
            return None, None
        if png is None:
            return None, None

        embed, file = _recipe_card(self.item, rid, png, self.index, len(self.ids))
        self._sync_buttons()
        return embed, file

    def _sync_buttons(self):
        for child in self.children:
            if child.custom_id == "dcemi_prev":
                child.disabled = self.index == 0
            elif child.custom_id == "dcemi_next":
                child.disabled = self.index >= len(self.ids) - 1

    async def _go(self, interaction: discord.Interaction, delta: int):
        self.index = min(max(self.index + delta, 0), len(self.ids) - 1)
        await interaction.response.defer()
        embed, file = await self.render()
        if file is None:
            return await interaction.edit_original_response(
                content=":warning: Render failed.", embed=None, attachments=[], view=self)
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)
        return None

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="dcemi_prev", disabled=True)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, -1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="dcemi_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, +1)
