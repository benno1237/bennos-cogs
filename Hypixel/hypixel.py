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
from typing import Optional, Tuple, Final, Union, List, Any

from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.chat_formatting import box

from .utils.abc import CompositeMetaClass, MixinMeta
from .utils.enums import gamemodes, scope

INVALID_API_KEY: Final = "Invalid API key"
USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36"


class Autostats():
    def __init__(self,
                 cog,
                 channel: discord.TextChannel,
                 gamemode: gamemodes,
                 user_data: dict,
                 apikey: str,
                 current_modules: list,
                 custom_modules: dict
            ):
        self.channel: discord.TextChannel = channel
        self.gamemode: gamemodes = gamemode
        self.user_data: list = user_data
        self.current_modules: list = current_modules
        self.custom_modules: dict = custom_modules
        self.cog: Hypixel = cog
        self.messages: list = []
        self.apikey: str = apikey

        self.task: asyncio.Task

    async def is_updated(self):
        stats, xp, _ = await self.cog.uuid_to_stats(
            uuid=self.user_data[0]["uuid"],
            gamemode=self.gamemode,
            active_modules=self.current_modules,
            custom_modules=self.custom_modules,
            apikey=self.apikey
        )

        if stats != self.user_data[0]["stats"]:
            self.user_data[0]["stats"] = stats
            self.user_data[0]["xp"] = xp
            return True
        else:
            return False

    async def main(self):
        while not self.task.cancelled():
            previous = self.user_data[0]["stats"]
            if await self.is_updated():
                await self.maybe_delete_old_messages()
                im_list = []

                for idx, user in enumerate(self.user_data):
                    if idx:
                        previous = self.user_data[idx]["stats"]
                        stats, xp, _ = await self.cog.uuid_to_stats(
                            uuid=user["uuid"],
                            gamemode=self.gamemode,
                            active_modules=self.current_modules,
                            custom_modules=self.custom_modules,
                            apikey=self.apikey
                        )

                        self.user_data[idx]["stats"] = stats
                        self.user_data[idx]["xp"] = xp

                    im_list.append(await self.cog.create_stats_img(
                        user_data=user,
                        gamemode=self.gamemode,
                        compare_stats=previous
                    ))

                self.messages = await self.cog.maybe_send_images(self.channel, im_list)
            await asyncio.sleep(10)

    async def maybe_delete_old_messages(self):
        try:
            await self.channel.delete_messages(messages=self.messages)
            self.messages = []
        except (discord.Forbidden, discord.NotFound):
            pass

    async def start(self):
        im_list = []
        for user in self.user_data:
            im_list.append(await self.cog.create_stats_img(user_data=user, gamemode=self.gamemode))

        self.messages = await self.cog.maybe_send_images(self.channel, im_list)

        self.task = asyncio.create_task(self.main())

    async def cancel(self):
        await self.maybe_delete_old_messages()
        self.task.cancel()
        del self


class SelectionRow(discord.ui.Select):
    def __init__(self, current_modules: list, author: discord.Member, config: Config, gamemode: gamemodes):
        self.config = config
        self.gamemode = gamemode
        self.author = author
        self.current_modules = current_modules

        options = []
        for i in current_modules:
            options.append(discord.SelectOption(label=i[0], description=i[1]))

        super().__init__(
            placeholder="Select the modules in the order you want...",
            options=options,
            min_values=len(current_modules),
            max_values=len(current_modules)
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.author:
            modules_raw = self.values
            new_modules = []
            db_keys = [x[0] for x in self.current_modules]

            for module in modules_raw:
                idx = db_keys.index(module)
                new_modules.append(self.current_modules[idx])

            await self.config.guild(interaction.guild).set_raw(self.gamemode.value, "current_modules", value=new_modules)
            await interaction.response.send_message("Order changed.")
            self.view.stop()


class Hypixel(commands.Cog, MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=365911945565569036, force_registration=True)
        self.session = aiohttp.ClientSession()

        self.autostats_tasks = {
            s.value: {} for s in scope
        }

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
                    "current_modules": [
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
                    "current_modules": [],
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

        asyncio.create_task(self.fetch_modules())


    """Api requests"""
    async def request_hypixel(self, ctx: commands.Context = None, uuid: str = None, topic: str = "player", apikey: str = None) -> Tuple[Optional[dict], Optional[int]]:
        if not apikey:
            apikey, _ = await self.fetch_apikey(ctx)

        url = f"https://api.hypixel.net/{topic}"

        if uuid:
            url += f"?uuid={uuid}"

        headers = {
            "API-Key": apikey,
            "User-Agent": USER_AGENT
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
            "User-Agent": USER_AGENT
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
    @commands.guild_only()
    @commands.group(name="autostats", invoke_without_command=True)
    async def command_autostats(self, ctx: commands.Context, gamemode: gamemodes, *usernames: str) -> None:
        """Base command for autostats processes"""
        user_data = await self.username_list_to_data(ctx, gamemode, usernames)

        current_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "current_modules")
        custom_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "custom_modules")
        apikey, key_scope = await self.fetch_apikey(ctx)

        autostats_task = Autostats(
            self,
            ctx.channel,
            gamemode,
            user_data,
            apikey,
            current_modules,
            custom_modules
        )

        if key_scope == scope.GUILD:
            if len(self.autostats_tasks[key_scope.value]) >= 5:
                await ctx.send("Already 5 autostats tasks running on the guild apikey. "
                               f"Set your own apikey using `{ctx.clean_prefix}hypixelset apikey`")
                return

        self.autostats_tasks[key_scope.value][ctx.author.id] = autostats_task
        await autostats_task.start()

    @command_autostats.group(name="stop", invoke_without_command=True)
    async def command_autostats_stop(self, ctx: commands.Context) -> None:
        """Stop you current autostats process"""
        for s in scope:
            if ctx.author.id in self.autostats_tasks[s.value].keys():
                await self.autostats_tasks[s.value][ctx.author.id].cancel()
                del self.autostats_tasks[s.value][ctx.author.id]
                await ctx.tick()
                return

        await ctx.send("No running autostats tasks")

    @command_autostats_stop.command(name="all")
    async def command_autostats_stop_all(self, ctx: commands.Context, stop_scope: scope = True) -> None:
        """Stop all autostats processes"""
        if self.bot.is_owner(ctx.author) or ctx.guild.owner == ctx.author:
            if stop_scope == scope.GUILD:
                for task in self.autostats_tasks[stop_scope.value].values():
                    await task.cancel()

        if self.bot.is_owner(ctx.author):
            for task in self.autostats_tasks[stop_scope.value].values():
                await task.cancel()

    @commands.command(name="gamemodes")
    async def command_gamemodes(self, ctx) -> None:
        """Lists all available gamemodes"""
        embed = discord.Embed(
            description=" \n".join([gamemode.value for gamemode in gamemodes]),
            color=await ctx.embed_colour()
        )

        await ctx.maybe_send_embed("\n".join([gamemode.value for gamemode in gamemodes]))

    @commands.group(name="hypixelset")
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        pass

    @commands.dm_only()
    @command_hypixelset.command(name="apikey")
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, guild: discord.Guild = None) -> None:
        resp, status = await self.request_hypixel(ctx=ctx, topic="key", apikey=apikey)

        if status == 200:
            if not guild:
                await self.config.user(ctx.author).apikey.set(apikey)
            else:
                await self.config.guild(guild).apikey.set(apikey)

            await ctx.tick()

        elif status == 403 and resp["cause"] == INVALID_API_KEY:
            await ctx.send("This apikey doesn't seem to be valid!")

    @command_hypixelset.command(name="color", aliases=["colour"])
    async def command_hypixelset_color(self, ctx: commands.Context, color: str) -> None:
        """Custom header color"""
        pass

    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.group(name="modules")
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        """Base command for managing modules"""
        pass

    @command_hypixelset_modules.command(name="add")
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gamemode: gamemodes, db_key: str, clear_name: str) -> None:
        """Add a module for the given gamemode"""
        guild_data = await self.config.guild(ctx.guild).get_raw(gamemode.value)

        current_modules = guild_data["current_modules"]
        custom_modules = guild_data["custom_modules"]

        if db_key in self.all_modules[gamemode.value] or db_key in custom_modules.keys():
            if db_key in [x[0] for x in current_modules]:
                await ctx.send(f"This module is already added.")
                return

            current_modules.append((db_key, clear_name))
            await self.config.guild(ctx.guild).set_raw(gamemode.value, "current_modules", value=current_modules)
            await ctx.send(f"Module `{db_key}` added as `{clear_name}`")
        else:
            await ctx.send(f"Module `{db_key}` doesn't seem to be valid.\n"
                           f"Use `{ctx.clean_prefix}hypixelset modules list {gamemode.value}` to retrieve a list of supported ones")

    @command_hypixelset_modules.command(name="remove")
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gamemode: gamemodes, db_key: str = None, clear_name: str = None) -> None:
        """Remove a module for the given gamemode"""
        if not db_key and not clear_name:
            await ctx.send_help()
            return

        current_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "current_modules")
        db_keys = [x[0] for x in current_modules]
        clear_names = [x[1] for x in current_modules]

        if db_key in db_keys:
            idx = db_keys.index(db_key)
            db_keys.pop(idx)
            clear_names.pop(idx)

        if clear_name in clear_names:
            idx = clear_names.index(clear_name)
            clear_names.pop(idx)
            db_keys.pop(idx)

        if len(db_keys) != len(current_modules):
            current_modules = [(x, clear_names[idx]) for idx, x in enumerate(db_keys)]
            await self.config.guild(ctx.guild).set_raw(gamemode.value, "current_modules", value=current_modules)
            await ctx.tick()
        else:
            await ctx.send("No matching module found to remove")

    @command_hypixelset_modules.command(name="reorder")
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, gamemode: gamemodes) -> None:
        current_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "current_modules")

        view = discord.ui.View()
        view.add_item(SelectionRow(current_modules, ctx.author, self.config, gamemode))

        await ctx.send("Select the modules in your preferred order: ", view=view)

    @command_hypixelset_modules.command(name="list")
    async def command_hypixelset_modules_list(self, ctx: commands.Context, gamemode: gamemodes) -> None:
        """List all modules of a gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "custom_modules")

        modules_gamemode = self.all_modules[gamemode.value] + [x[0] for x in custom_modules]
        modules_gamemode = "\n".join(list(map(str, modules_gamemode)))

        await ctx.send(file=discord.File(BytesIO(modules_gamemode.encode()), "modules.txt"))

    @commands.guild_only()
    @command_hypixelset.command(name="username", aliases=["name"])
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        resp, status = await self.request_mojang(username)
        if status == 200 and resp.get("id", None):
            await self.config.user(ctx.author).uuid.set(resp["id"])
            await ctx.tick()

    @commands.guild_only()
    @commands.command(name="stats")
    async def command_stats(self, ctx, gamemode: gamemodes, *usernames: str) -> None:
        async with ctx.typing():
            user_data = await self.username_list_to_data(ctx, gamemode=gamemode, username_list=usernames)

            im_list = []
            for user in user_data:
                im_list.append(await self.create_stats_img(user, gamemode))

            await self.maybe_send_images(ctx.channel, im_list)

    """Converters"""
    async def username_list_to_data(self, ctx, gamemode: gamemodes, username_list: list) -> list:
        if ctx.guild:
            guild_data = await self.config.guild(ctx.guild).all()
            active_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "current_modules")
            custom_modules = await self.config.guild(ctx.guild).get_raw(gamemode.value, "custom_modules")
        else:
            guild_data = None
            header_color = tuple(await self.config.header_color())

        if not username_list:
            username_list = [str(ctx.author.id)]

        user_data = []
        failed = []
        async for username in AsyncIter(username_list):
            #trying a direct request first
            if 16 >= len(username) >= 3:
                uuid_resp, status = await self.request_mojang(username)
                if uuid_resp and status == 200:
                    try:
                        data, xp, username = await self.uuid_to_stats(uuid_resp["id"], gamemode, active_modules, custom_modules, ctx=ctx)

                        user_data.append({
                            "stats": data,
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

                data, xp, username = await self.uuid_to_stats(user_conf["uuid"], gamemode, active_modules, custom_modules, ctx=ctx)
                user_data.append({
                    "stats": data,
                    "header_color": (tuple(user_conf["header_color"])
                                     if user_conf["header_color"]
                                     else tuple(guild_data["header_color"])
                                        if guild_data["header_color"]
                                        else header_color),
                    "username": username,
                    "uuid": user_conf["uuid"],
                    "skin": user_conf["skin"],
                    "xp": xp
                })

            except commands.BadArgument:
                failed.append(username)

        if failed:
            text = box("\n".join(failed))
            await ctx.send("Stats for the following users couldn't be fetched. "
                           "Make sure a username is set if you pass a discord user. \n\n"
                            f"{text}")

        return user_data

    async def uuid_to_stats(self,
                            uuid: str,
                            gamemode: gamemodes,
                            active_modules: list,
                            custom_modules: dict,
                            ctx: commands.Context = None,
                            apikey: str = None) -> Optional[Tuple[List[Tuple[str, str]], Any, Any]]:
        resp, status = await self.request_hypixel(ctx=ctx, uuid=uuid, apikey=apikey)
        if status == 200:
            gamemode_data = resp["player"]["stats"][gamemode.value]

            stats = []
            for module in active_modules:
                if module[0] in custom_modules.keys():
                    value = self.calculate_custom_value(custom_modules[module[0]], gamemode_data)
                else:
                    value = gamemode_data.get(module[0], 0)
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
        for s in scope:
            for task in self.autostats_tasks[s.value].values():
                await task.cancel()

        await self.session.close()


    """Image gen"""
    async def create_stats_img(self, user_data: dict, gamemode: gamemodes, compare_stats: list = None) -> Image.Image:
        datapath: pathlib.Path = cog_data_path(self)
        background_path: pathlib.Path = datapath / "backgrounds"

        color_header_stats = (255, 145, 0)
        color_body_stats = (255, 200, 0)

        #take care of the background image
        def background_im():
            background = random.choice([file for file in background_path.iterdir() if file.is_file()])
            im_background = Image.open(background).convert("RGBA")
            im_background = ImageEnhance.Brightness(im_background).enhance(0.3)
            im_background = im_background.filter(ImageFilter.GaussianBlur(im_background.width / 300))
            return im_background

        im_background = await self.bot.loop.run_in_executor(
            None,
            background_im
        )

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

        def generate_image(im_skin):
            #fetch available fonts
            font_header_player_path = self.fetch_font(datapath, "header_player")
            font_header_stats_path = self.fetch_font(datapath, "header_stats")
            font_body_stats_path = self.fetch_font(datapath, "body_stats")

            font_header_player = ImageFont.truetype(str(font_header_player_path), int(im_background.height / 6.5))
            font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(im_background.height / 8))

            modules_left = int(len(user_data["stats"]) / 2 + 1) if len(user_data["stats"]) % 2 else int(len(user_data["stats"]) / 2)

            height = int(im_background.height / 1.4)
            width = int(height * (im_skin.width / im_skin.height))
            im_skin = im_skin.resize((width, height), resample=Image.BOX)

            if len(user_data["stats"]) > 5:
                x = int((im_background.width / 2) - (im_skin.width / 2))
                stats_box = (
                    im_background.width / 2 - im_skin.width / 2 - im_background.width / 15,
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

            longest_item = max([x[0] for x in user_data["stats"]], key=len)
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
            compare_anchor = "rm"
            x = int(im_background.width / 25)
            header_margin = int(font_header_player.size + im_background.height / 100)
            for i in range(0, len(user_data["stats"])):
                try:
                    y = y_pos[i] + header_margin
                except IndexError:
                    y = y_pos[i - modules_left] + header_margin

                if i == modules_left:
                    anchor = "rm"
                    compare_anchor = "lm"
                    x = int(im_background.width * 0.96)

                draw.text(
                    (x, y),
                    user_data["stats"][i][0],
                    fill=color_header_stats,
                    font=font_header_stats,
                    anchor=anchor
                )

                draw.text(
                    (x, y + font_header_stats.size * 0.9),
                    user_data["stats"][i][1],
                    fill=color_body_stats,
                    font=font_body_stats,
                    anchor=anchor
                )

                if compare_stats:
                    compare_value, compare_color = self.get_compare_value_and_color(compare_stats[i], user_data["stats"][i][1])

                    draw.text(
                        (stats_box[0] - x, y),
                        compare_value,
                        fill=compare_color,
                        anchor=compare_anchor
                    )

            xp_bar_im = self.render_xp_bar(gamemode, user_data["xp"], im_background.size)
            im_background.alpha_composite(xp_bar_im, (0, 0))

        await self.bot.loop.run_in_executor(
            None,
            generate_image,
            im_skin
        )

        return im_background

    def fetch_font(self, path: pathlib.Path, query: str) -> pathlib.Path:
        path = path / "fonts"
        for file in path.iterdir():
            if file.is_file() and query in file.stem:
                return file
        else:
            raise ValueError(f"Font {query} not found.")

    def get_compare_value_and_color(self, module: tuple, original_value: Union[Any]) -> Tuple[Union[Any], Tuple]:
        if isinstance(original_value, str):
            return module[1], None

        green = (0, 255, 0)
        red = (255, 0, 0)
        negative_list = [
            "loss"
        ]
        compare = module[1] - original_value

        if compare == 0:
            return compare, None

        elif compare < 0 :
            if module[0] in negative_list:
                return compare, red
            return compare, green

        else:
            if module[0] in negative_list:
                return compare, green
            return compare, red

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
        xps = [0, 20, 70, 150, 250, 500, 1000, 2000, 3500, 5000, 10000, 15000]
        easy_xp_skywars = 0
        for i in xps:
            easy_xp_skywars += i
        if xp >= 15000:
            level = (xp - 15000) / 10000 + 12
            percentage = level % 1.0
            return int(level), percentage
        else:
            for i in range(len(xps)):
                if xp < xps[i]:
                    level = i + float(xp - xps[i - 1]) / (xps[i] - xps[i - 1])
                    percentage = level % 1.0
                    return int(level), percentage

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
            return guild_key, scope.GLOBAL
        else:
            return user_key, scope.USER

    async def fetch_modules(self) -> None:
        """Fetch all available hypixel modules"""
        headers = {
            "USER_AGENT": USER_AGENT
        }

        async with self.session.get(
            "https://raw.githubusercontent.com/HypixelDatabase/HypixelTracking/master/API/player.json",
            headers=headers,
        ) as resp:
            if resp.status == 200:
                resp = json.loads(await resp.text())

        self.all_modules = {}
        for gamemode, modules in resp["player"]["stats"].items():
            self.all_modules[gamemode.lower()] = [x for x in modules.keys() if isinstance(x, str) or isinstance(x, int)]

    async def maybe_send_images(self, channel: discord.TextChannel, im_list: List[Image.Image]) -> discord.Message:
        """Try to send a list of images to the given channel
        Warns if a permission error occurs"""
        def generate_im_list():
            im_binary_list = []

            for idx, im in enumerate(im_list):
                with BytesIO() as imb:
                    im.save(imb, "PNG")
                    imb.seek(0)
                    im_binary_list.append(discord.File(imb, f"stats{idx}.png"))

            return im_binary_list

        im_binary_list = await self.bot.loop.run_in_executor(
            None,
            generate_im_list
        )

        messages = []
        for i in range(0, len(im_binary_list), 10):
            try:
                messages.append(await channel.send(files=im_binary_list[i: i + 10]))
            except discord.Forbidden:
                messages.append(await channel.send("Looks like i do not have the proper permission to send attachments to this channel"))

        # return messages

    def wins_key_for_gamemode(self, gamemode: gamemodes) -> Optional[Any]:
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
