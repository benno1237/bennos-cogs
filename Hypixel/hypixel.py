import aiohttp
import asyncio
import base64
import copy
import discord
import io
import json
import MinePI
import pathlib
import random

from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from typing import Optional, Tuple, Final, Union

from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.data_manager import cog_data_path, bundled_data_path

from .utils.abc import CompositeMetaClass, MixinMeta
from .utils.enums import gamemodes

INVALID_API_KEY: Final = "Invalid API key"

class Hypixel(commands.Cog, MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=365911945565569036, force_registration=True)
        self.session = aiohttp.ClientSession()

        default_global = {
            "header_color": [255, 0, 0]
        }

        default_user = {
            "apikey": None,
            "header_color": None,
            "skin": None,
            "uuid": None,
        }

        gamemode_data = {}
        for gamemode in gamemodes:
            if gamemode == gamemodes.BEDWARS: #default modules for bedwars
                gamemode_data[gamemode.value] = {
                    "enabled_modules": [
                        ("games_played_bedwars", "Games played"),
                        ("kills_bedwars", "Kills"),
                        ("normal_kd", "KD"),
                        ("beds_broken_bedwars", "Beds broken"),
                        ("wins_bedwars", "Wins"),
                        ("winstreak", "Winstreak"),
                        ("final_kills_bedwars", "Final kills"),
                        ("final_kd", "Final KD")
                    ],
                    "custom_modules": {
                        "wl_rate": "round((gamemode_stats['wins_bedwars'] / gamemode_stats['losses_bedwars']), 2)",
                        "normal_kd": "round((gamemode_stats['kills_bedwars'] / gamemode_stats['deaths_bedwars']), 2)",
                        "final_kd": "round((gamemode_stats['final_kills_bedwars'] / gamemode_stats['final_deaths_bedwars']), 2)",
                    },
                }
            else: #no defaults present for the rest (mainly because i never played them)
                gamemode_data[gamemode.value] = {
                    "enabled_modules": [],
                    "custom_modules": {},
                }

        default_guild = {
            "apikey": None,
            "header_color": [255, 0, 0],
            **gamemode_data
        }

        self.config.register_global(**default_global)
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

    """Api requests"""
    async def request_hypixel(self, ctx, uuid: str = None, topic: str = "player", apikey: str = None) -> Tuple[Optional[dict], Optional[int]]:
        if not apikey:
            apikey = await self.fetch_apikey(ctx)

        url = f"https://api.hypixel.net/{topic}"

        if uuid:
            url += f"?uuid={uuid}"

        headers = {
            "API-Key": apikey,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36"
        }

        async with self.session.get(url=url, headers=headers) as resp:
            try:
                resp_dict = json.loads(await resp.text())

                if topic == "player":
                    for key, value in copy.copy(resp_dict["player"]["stats"]).items():
                        resp_dict["player"]["stats"][key.lower()] = value

                return resp_dict, resp.status
            except json.JSONDecodeError:
                #invalid response?
                return None, resp.status
            except AttributeError:
                #api down again?
                return None, resp.status
            except asyncio.TimeoutError:
                #api down again?
                return None, None

    async def request_mojang(self, mc_name: str) -> Tuple[Optional[dict], Optional[int]]:
        url = f"https://api.mojang.com/users/profiles/minecraft/{mc_name}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36"
        }
        async with self.session.get(url=url, headers=headers) as resp:
            try:
                resp_dict = json.loads(await resp.text())
                return resp_dict, resp.status
            except json.JSONDecodeError:
                # invalid response?
                return None, resp.status
            except asyncio.TimeoutError:
                #api down again?
                return None, None


    """Commands"""
    @commands.group(name="hypixelset")
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        pass

    @commands.dm_only()
    @command_hypixelset.command(name="apikey")
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, guild: discord.Guild = None) -> None:
        resp, status = await self.request_hypixel(ctx, topic="key", apikey=apikey)

        if status == 200:
            if not guild:
                await self.config.user(ctx.author).apikey.set(apikey)
            else:
                await self.config.guild(guild).apikey.set(apikey)

            await ctx.tick()

        elif status == 403 and resp["cause"] == INVALID_API_KEY:
            await ctx.send("This apikey doesn't seem to be valid!")

    @commands.command(name="stats")
    async def command_stats(self, ctx, gamemode: gamemodes, *usernames: str):
        user_data = await self.username_list_to_data(ctx, gamemode=gamemode, username_list=usernames)

        for user in user_data:
            im = await self.create_stats_img(user, gamemode)

            await self.maybe_send_image(ctx.channel, im)


    """Converters"""
    async def username_list_to_data(self, ctx, gamemode: gamemodes, username_list: list) -> list:
        if ctx.guild:
            guild_data = await self.config.guild(ctx.guild).all()
            active_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "enabled_modules")
            custom_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "custom_modules")
        else:
            guild_data = None
            header_color = tuple(await self.config.header_color())

        user_data = []
        failed = []
        async for username in AsyncIter(username_list):
            #trying a direct request first
            uuid_resp, status = await self.request_mojang(username)
            if uuid_resp and status == 200:
                try:
                    data, xp, username = await self.uuid_to_stats(ctx, uuid_resp["id"], gamemode, active_modules, custom_modules)

                    user_data.append({
                        "data": data,
                        "header_color": tuple(guild_data["header_color"]) if guild_data else header_color,
                        "username": username,
                        "uuid": uuid_resp["id"],
                        "skin": None,
                        "xp": xp
                    })
                    continue
                except ValueError:
                    pass

            #if it fails, try to convert the username to a discord.User object
            try:
                user_obj = await commands.UserConverter().convert(ctx, username)
                user_conf = await self.config.user(user_obj).all()

                if not user_conf["uuid"]:
                    failed.append(username)
                    continue

                data, xp, username = await self.uuid_to_stats(ctx, user_conf["uuid"], gamemode, active_modules, custom_modules)
                user_data.append({
                    "data": data,
                    "header_color": (tuple(user_conf["header_color"])
                                     if user_conf["header_color"]
                                     else tuple(guild_data["header_color"])
                                        if guild_data["header_color"]
                                        else header_color),
                    "username": username,
                    "uuid": user_conf["uuid"],
                    "skin": user_data["skin"],
                    "xp": xp
                })

            except commands.BadArgument:
                failed.append(username)

        return user_data

    async def uuid_to_stats(self, ctx, uuid: str, gamemode: gamemodes, active_modules: list, custom_modules: dict) -> list:
        resp, status = await self.request_hypixel(ctx, uuid=uuid)
        if status == 200:
            gamemode_data = resp["player"]["stats"][gamemode.value]

            stats = []
            for module in active_modules:
                if module[0] in custom_modules.keys():
                    value = self.calculate_custom_value(custom_modules[module[0]], gamemode_data)
                else:
                    value = gamemode_data[module[0]]
                stats.append((str(module[1]), str(value)))

            return stats, gamemode_data[self.xp_key_for_gamemode(gamemode)], resp["player"]["playername"]

        return None


    """Dpy Events"""
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if self.command_hypixelset in [ctx.command, ctx.command.root_parent]:
            return

        user_key = await self.config.user(ctx.author).apikey()
        if not ctx.guild and not user_key:
            await ctx.send("No personal apikey set!")
            raise commands.CheckFailure()

        elif not user_key and not await self.config.guild(ctx.guild).apikey():
            await ctx.send("No personal or guild apikey set!")
            raise commands.CheckFailure()


    def cog_unload(self) -> None:
        asyncio.create_task(self.cog_unload_task())

    async def cog_unload_task(self) -> None:
        await self.session.close()


    """Image gen"""
    async def create_stats_img(self, user_data: dict, gamemode: gamemodes) -> Image.Image:
        datapath: pathlib.Path = cog_data_path(self)
        background_path: pathlib.Path = datapath / "backgrounds"

        #take care of the background image
        background = random.choice([file for file in background_path.iterdir() if file.is_file()])
        im_background = Image.open(background).convert("RGBA")
        im_background = ImageEnhance.Brightness(im_background).enhance(0.3)
        im_background = im_background.filter(ImageFilter.GaussianBlur(im_background.width / 300))

        #fetch available fonts
        font_header_player_path = self.fetch_font(datapath, "header_player")
        font_header_stats_path = self.fetch_font(datapath, "header_stats")
        font_body_stats_path = self.fetch_font(datapath, "body_stats")

        font_header_player = ImageFont.truetype(str(font_header_player_path), int(im_background.height / 6.5))
        font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(im_background.height / 8))

        modules_left = int(len(user_data["data"]) / 2 + 1) if len(user_data["data"]) % 2 else int(len(user_data["data"]) / 2)

        pos = random.choice([
            (-25, -25, 20, 5, -2, -20, 2),
            (-25, 25, 20, 5, -2, 20, -2),
            (-5, 25, 10, 5, -2, 5, -5),
            (-5, -25, 10, 5, -2, -5, 5),
            (0, 0, 0, 0, 0, 0, 0),
        ])
        im_skin = await MinePI.render_3d_skin(
            user_data["uuid"],
            *pos,
            12,
            True,
            True,
            False,
            skin_image=user_data["skin"]
        )

        height = int(im_background.height / 1.4)
        width = int(height * (im_skin.width / im_skin.height))
        im_skin = im_skin.resize((width, height), resample=Image.BOX)

        if len(user_data["data"]) > 5:
            x = int((im_background.width / 2) - (im_skin.width / 2))
            stats_box = (
                im_background.width / 2 - im_skin.width / 2 - im_background.width / 25,
                im_background.height - (font_header_player.size * 2)
            )
        else:
            x = int(im_background.width - (im_skin.width * 1.5))
            stats_box = (
                im_background.width - im_skin.width - im_skin.width * 1.5 - im_background.width / 25,
                im_background.height - (font_header_player.size * 2)
            )

        im_background.alpha_composite(im_skin, (x, int(im_background.height / 6.5) + int(im_background.height / 200)))
        draw = ImageDraw.Draw(im_background)

        y_pos = []

        spacing = stats_box[1] / modules_left
        if modules_left % 2:
            for i in range(int(modules_left / 2) + 1):
                y_pos.append(stats_box[1] / 2 + spacing * i)
                if i:
                    y_pos.append(stats_box[1] / 2 - spacing * i)
        else:
            for i in range(int(modules_left / 2)):
                y_pos.append(stats_box[1] / 2 + spacing * 0.5 + spacing * i)
                y_pos.append(stats_box[1] / 2 - spacing * 0.5 - spacing * i)

        y_pos = sorted(y_pos)

        longest_item = max([x[0] for x in user_data["data"]], key=len)
        length = font_header_stats.getlength(longest_item)
        if length > stats_box[0]:
            font_size = font_header_stats.size * (stats_box[0] / length)
            del font_header_stats
            font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(font_size))

        font_body_stats = ImageFont.truetype(str(font_body_stats_path), int(font_header_stats.size * 0.95))

        draw.text(
            ((im_background.width / 2), im_background.height / 100),
            user_data["username"],
            fill=user_data["header_color"],
            font=font_header_player,
            anchor="mt"
        )
        anchor = "lm"
        x = int(im_background.width / 25)
        header_margin = int(font_header_player.size + im_background.height / 100)
        for i in range(0, len(user_data["data"])):
            try:
                y = y_pos[i] + header_margin
            except IndexError:
                y = y_pos[i - modules_left] + header_margin

            if i == modules_left:
                anchor = "rm"
                x = int(im_background.width * 0.96)

            draw.text(
                (x, y),
                user_data["data"][i][0],
                fill=(255, 145, 0),
                font=font_header_stats,
                anchor=anchor
            )

            draw.text(
                (x, y + font_header_stats.size * 1.05),
                user_data["data"][i][1],
                fill=(255, 200, 0),
                font=font_body_stats,
                anchor=anchor
            )

        xp_bar_im = self.render_xp_bar(gamemode, user_data["xp"], im_background.size)
        im_background.alpha_composite(xp_bar_im, (0, 0))

        return im_background

    def fetch_font(self, path: pathlib.Path, query: str) -> pathlib.Path:
        path = path / "fonts"
        for file in path.iterdir():
            if file.is_file() and query in file.stem:
                return file
        else:
            raise ValueError(f"Font {query} not found.")

    def get_level_bedwars(self, xp: int) -> Tuple[int, float]:
        def xp_for_level():
            if level == 0:
                return 0

            respected_level = level_respecting_prestige()

            if respected_level > easy_levels:
                return 5000
            else:
                return level_scale.get(respected_level, 0)

        def level_respecting_prestige():
            if level > (highest_prestige * levels_per_prestige):
                return level - (highest_prestige * levels_per_prestige)
            else:
                return level % levels_per_prestige

        easy_levels = 4
        level_scale = {1: 500, 2: 1000, 3: 2000, 4: 3500}
        easy_levels_xp = sum(level_scale.values())
        xp_per_prestige = 96 * 5000 + easy_levels_xp
        levels_per_prestige = 100
        highest_prestige = 10

        prestiges = int(xp / xp_per_prestige)
        level = prestiges * levels_per_prestige
        xp_without_prestige = xp - (prestiges * xp_per_prestige)

        for i in range(1, easy_levels + 1):
            xp_for_easy_level = xp_for_level()
            if xp_without_prestige < xp_for_easy_level:
                break

            level += 1
            xp_without_prestige -= xp_for_easy_level

        level_total = int(level + xp_without_prestige / 5000)
        if level_total % 100 > 4:
            xp_for_easy_level = 5000
        percentage = (level + xp_without_prestige / xp_for_easy_level) % 1.0
        return level_total, percentage

    def get_level_skywars(self, xp: int) -> Tuple[int, float]:
        pass

    def render_xp_bar(self, gamemode: gamemodes, xp: int, size: tuple):
        im = Image.new("RGBA", size)
        draw = ImageDraw.Draw(im)

        level, percentage = getattr(self, f"get_level_{gamemode.value}")(xp)

        line_thickness = int(size[1] / 216)
        spacing = int(size[1] / 54)
        x = int(size[0] / 7)
        y = int(size[1] - size[1] / 21) + spacing
        bar_color = "#40D433"
        line_color = "#9E9E9E"

        draw.line(
            ((x, y - spacing * 0.5), (x + (size[0] - x * 2), y - spacing * 0.5)),
            fill=line_color,
            width=spacing
        )
        draw.line(
            ((x, y - spacing * 0.5), (x + ((size[0] - x * 2) * percentage), y - spacing * 0.5)),
            fill=bar_color,
            width=spacing
        )

        draw.line(
            ((x, y), (size[0] - x, y)),
            fill=0,
            width=line_thickness
        )
        draw.line(
            ((x, y - spacing), (size[0] - x, y - spacing)),
            fill=0,
            width=line_thickness
        )

        for i in range(19):
            x_grid = x + i * ((size[0] - x * 2) / 18)
            draw.line(
                ((x_grid, y), (x_grid, y - spacing)),
                fill=0,
                width=line_thickness
            )

        font_size = int(size[1] / 20)
        font_xp_path = self.fetch_font(cog_data_path(self), "xp")
        font_xp = ImageFont.truetype(str(font_xp_path), font_size)

        draw.text(
            (size[0] / 2, y - spacing * 1.4),
            text=str(level),
            font=font_xp,
            fill=bar_color,
            anchor="mb"
        )

        return im

    """Utility functions"""
    def calculate_custom_value(self, custom_module: str, gamemode_stats: dict) -> Union[float, int]:
        try:
            return eval(custom_module)
        except KeyError:
            return 0

    async def fetch_apikey(self, ctx: commands.Context) -> Optional[str]:
        """Guild/User based apikey lookup"""
        user_key = await self.config.user(ctx.author).apikey()
        if not user_key and ctx.guild:
            guild_key = await self.config.guild(ctx.guild).apikey()
            return guild_key
        else:
            return user_key

    async def maybe_send_image(self, channel: discord.TextChannel, im: Image.Image) -> discord.Message:
        """Try to send the image to the given channel
        Warns if a permission error occurs"""
        with BytesIO() as imb:
            im.save(imb, "PNG")
            imb.seek(0)

            try:
                m = await channel.send(file=discord.File(fp=imb, filename="stats.png"))
            except discord.Forbidden:
                m = await channel.send("Looks like i do not have the proper permission to send attachments to this channel")

            return m

    def wins_key_for_gamemode(self, gamemode: gamemodes) -> Optional[str]:
        """Returns the hypixel wins api key for the given gamemode"""
        if gamemode == gamemodes.BEDWARS:
            return "wins_bedwars"
        elif gamemode == gamemodes.MCGO:
            return "game_wins"
        elif gamemode == gamemodes.VAMPIREZ:
            return ["vampire_wins", "human_wins"]
        elif gamemode in gamemodes:
            return "wins"
        else:
            return None

    def xp_key_for_gamemode(self, gamemode: gamemodes) -> Optional[str]:
        """Returns the hypixel experience api key for the given gamemode"""
        if gamemode == gamemodes.BEDWARS:
            return "Experience"
        elif gamemode == gamemodes.SKYWARS:
            return "skywars_experience"
        else:
            return None
