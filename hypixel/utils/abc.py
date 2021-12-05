import aiohttp
import discord
import pathlib
import asyncio

from abc import ABC, abstractmethod
from PIL import Image
from typing import Optional, Tuple, Union, List, Any, Literal

from redbot.core import commands, Config
from redbot.core.bot import Red

from .enums import Gamemode, Gamemodes


class MixinMeta(ABC):
    bot: Red
    config: Config
    ctx: commands.Context
    session: aiohttp.ClientSession
    cog_ready_event: asyncio.Event

    modules: dict
    autostats_tasks: dict

    """Commands"""
    @abstractmethod
    async def command_autostats(self, ctx: commands.Context, gm: Gamemode, *usernames: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_autostats_stop(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_autostats_stop_all(self, ctx: commands.Context, scope_global: bool = True) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_gamemodes(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, guild: discord.Guild = None) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gm: Gamemodes, db_key: str, clear_name: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_create(self, ctx: commands.Context, gm: Gamemodes, db_key: str, *, calc: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_list(self, ctx: commands.Context, gm: Gamemodes) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gm: Gamemodes, db_key: str = None, clear_name: str = None) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, gm: Gamemodes) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_stats(self, ctx: commands.Context, gm: Gamemodes, *usernames: str) -> None:
        raise NotImplementedError()


    """Dpy Events"""
    @abstractmethod
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    def cog_unload(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord", "owner", "user", "user_strict"],
        user_id: int,
    ):
        raise NotImplementedError()


    """Image gen"""
    @abstractmethod
    async def create_stats_img(self, player: Any, gm: Gamemode, compare_stats: list = None) -> Image.Image:
        raise NotImplementedError()

    @abstractmethod
    def fetch_font(self, path: pathlib.Path, query: str) -> pathlib.Path:
        raise NotImplementedError()

    @abstractmethod
    def get_compare_value_and_color(
            self,
            module: Any,
            original_val: Optional[Union[int, float, str]],
            c_stats: dict
    ) -> Tuple[Any, Optional[Tuple]]:
        raise NotImplementedError()

    @abstractmethod
    def render_xp_bar_new(self, player) -> Image.Image:
        raise NotImplementedError()

    @abstractmethod
    def render_xp_bar(self, gm: Gamemode, xp: int, size: tuple) -> Image.Image:
        raise NotImplementedError()


    """Utils"""
    @abstractmethod
    async def fetch_modules(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def maybe_send_images(self, channel: discord.TextChannel, im: List[Image.Image]) -> List[discord.Message]:
        raise NotImplementedError()

    @abstractmethod
    async def send_failed_for(self, ctx: commands.Context, users: List) -> None:
        raise NotImplementedError()


class CompositeMetaClass(type(commands.Cog), type(ABC)):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass
