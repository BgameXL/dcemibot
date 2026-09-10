"""DCEMI render EMI recipes as images, in discord.

Three slash commands, mirroring the DCEMI socket protocol:
  - `/recipe <item>` — the friendly one: autocompletes the item id, then pages
    through every recipe for that item with ◀ ▶ buttons (uses /list + /recipe +
    /render under the hood).
  - `/list <query>`  — search EMI's item index by substring (discovery).
  - `/render <recipe_id>` — render one recipe by its raw id (advanced/debug).

Connect-only: it talks to a running DCEMI renderer over TCP (DCEMI_HOST/
DCEMI_PORT, default 127.0.0.1:25599).
"""

import io

import discord
from discord import app_commands
from discord.ext import commands

from api import commands as apicommands
from . import client


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DCEMI(bot))


class DCEMI(apicommands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="recipe", description="Render a Minecraft recipe from EMI")
    @app_commands.describe(item="Item id, e.g. minecraft:iron_sword")
    async def recipe(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        try:
            ids = await client.recipes(item)
        except client.DcemiError as e:
            return await interaction.followup.send(f":warning: {e}")

        if isinstance(ids, dict) or not ids:
            return await interaction.followup.send(f"No recipes found for `{item}`.")

        view = RecipeView(item, ids)
        embed, file = await view.render()
        if file is None:
            return await interaction.followup.send(":warning: Failed to render recipe.")
        await interaction.followup.send(embed=embed, file=file, view=view)
        return None

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

        view = ListView(query, items)
        await interaction.followup.send(
            embed=view.embed(), view=view if view.pages > 1 else discord.utils.MISSING)
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

        file = discord.File(io.BytesIO(png), filename="recipe.png")
        embed = discord.Embed(title="Render", description=f"`{recipe_id}`")
        embed.set_image(url="attachment://recipe.png")
        await interaction.followup.send(embed=embed, file=file)
        return None


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

        file = discord.File(io.BytesIO(png), filename="recipe.png")
        embed = discord.Embed(title=self.item, description=f"`{rid}`")
        embed.set_footer(text=f"Recipe {self.index + 1}/{len(self.ids)}")
        embed.set_image(url="attachment://recipe.png")
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


class ListView(discord.ui.View):
    """Paginated view over /list results — a query like 'stone' can match 90+
    items, more than one Discord message can show, so page through them ◀ ▶."""

    PAGE_SIZE = 40

    def __init__(self, query: str, items: list[str]):
        super().__init__(timeout=300)
        self.query = query
        self.items = items
        self.page = 0
        self.pages = max(1, (len(items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def embed(self) -> discord.Embed:
        start = self.page * self.PAGE_SIZE
        chunk = self.items[start:start + self.PAGE_SIZE]
        body = "\n".join(f"`{i}`" for i in chunk)
        embed = discord.Embed(title=f"Items matching “{self.query}”", description=body)
        embed.set_footer(text=f"Page {self.page + 1}/{self.pages} · {len(self.items)} match(es)")
        self._sync_buttons()
        return embed

    def _sync_buttons(self):
        for child in self.children:
            if child.custom_id == "dcemi_list_prev":
                child.disabled = self.page == 0
            elif child.custom_id == "dcemi_list_next":
                child.disabled = self.page >= self.pages - 1

    async def _go(self, interaction: discord.Interaction, delta: int):
        self.page = min(max(self.page + delta, 0), self.pages - 1)
        await interaction.response.defer()
        await interaction.edit_original_response(embed=self.embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="dcemi_list_prev", disabled=True)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, -1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="dcemi_list_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, +1)
