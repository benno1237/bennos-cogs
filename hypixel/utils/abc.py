import aiohttp
import discord
import pathlib

from abc import ABC, abstractmethod
from PIL import Image
from typing import Optional, Tuple, Union, List, Any

from redbot.core import commands, Config
from redbot.core.bot import Red

from .enums import gamemodes


class MixinMeta(ABC):
    bot: Red
    config: Config
    ctx: commands.Context
    session: aiohttp.ClientSession

    all_modules: list
    autostats_tasks: dict

    """Api requests"""
    @abstractmethod
    async def request_hypixel(self, ctx: commands.Context, uuid: str, topic: str = "player", apikey: str = None) -> Tuple[Optional[dict], Optional[int]]:
        raise NotImplementedError()

    @abstractmethod
    async def request_mojang(self, mc_name: str) -> Tuple[Optional[dict], Optional[int]]:
        raise NotImplementedError()


    """Commands"""
    @abstractmethod
    async def command_autostats(self, ctx: commands.Context, gamemode: gamemodes, *usernames: str) -> None:
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
    async def command_hypixelset_color(self, ctx: commands.Context, color: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gamemode: gamemodes, db_key: str, clear_name: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gamemode: gamemodes, db_key: str = None, clear_name: str = None) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, gamemode: gamemodes) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_modules_list(self, ctx: commands.Context, gamemode: gamemodes) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def command_stats(self, ctx: commands.Context, gamemode: gamemodes, *usernames: str) -> None:
        raise NotImplementedError()


    """Converters"""
    @abstractmethod
    async def username_list_to_data(self, username_list: list) -> list:
        raise NotImplementedError()

    @abstractmethod
    async def uuid_to_stats(self, ctx: commands.Context, uuid: str, gamemode: gamemodes, active_modules: dict) -> dict:
        raise NotImplementedError()


    """Dpy Events"""
    @abstractmethod
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        raise NotImplementedError()

    @abstractmethod
    def cog_unload(self) -> None:
        raise NotImplementedError()


    """Image gen"""
    @abstractmethod
    async def create_stats_img(self, user_data: dict, gamemode: gamemodes, compare_stats: list = None) -> Image.Image:
        raise NotImplementedError()

    @abstractmethod
    def fetch_font(self, path: pathlib.Path, query: str) -> pathlib.Path:
        raise NotImplementedError()

    @abstractmethod
    def get_compare_value_and_color(self, module: Tuple, original_value: Union[Any]) -> Tuple[Union[Any], Tuple]:
        raise NotImplementedError()

    @abstractmethod
    def get_level_bedwars(self, xp: int) -> Tuple[int, float]:
        raise NotImplementedError()

    @abstractmethod
    def get_level_skywars(self, xp: int) -> Tuple[int, float]:
        raise NotImplementedError()

    @abstractmethod
    def render_xp_bar(self, gamemode: gamemodes, xp: int, size: tuple) -> Image.Image:
        raise NotImplementedError()


    """Utils"""
    @abstractmethod
    def calculate_custom_value(self, custom_module: str) -> Union[float, str]:
        raise NotImplementedError()

    @abstractmethod
    async def fetch_apikey(self, ctx: commands.Context) -> Optional[str]:
        raise NotImplementedError()

    @abstractmethod
    async def fetch_modules(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def maybe_send_images(self, channel: discord.TextChannel, im: List[Image.Image]) -> discord.Message:
        raise NotImplementedError()

    @abstractmethod
    def wins_key_for_gamemode(self, gamemode: gamemodes) -> Optional[str]:
        raise NotImplementedError()

    @abstractmethod
    def xp_key_for_gamemode(self, gamemode: gamemodes) -> Optional[str]:
        raise NotImplementedError()


class CompositeMetaClass(type(commands.Cog), type(ABC)):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """

    pass