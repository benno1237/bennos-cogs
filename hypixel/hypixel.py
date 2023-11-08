import aiohttp
import asyncio
import math
import discord
import json
import MinePI
import pathlib
import random
import re
import time
import tabulate

from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from typing import Optional, Tuple, Final, Union, List, Any, Literal

from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.data_manager import cog_data_path, bundled_data_path

from .utils.abc import CompositeMetaClass, MixinMeta
from .utils.enums import Gamemode, Gamemodes, Scope, ColorTypes, Ranks, Rank

INVALID_API_KEY: Final = "Invalid API key"


class ButtonConfirm(discord.ui.View):
    def __init__(self, author_id: int):
        self.author_id = author_id
        self.confirm = False
        super().__init__(timeout=30)

    def stop(self):
        self.clear_items()
        super().stop()

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.author_id == interaction.user.id:
            self.confirm = True
            self.stop()
        else:
            await interaction.response.send_message("You do not have permissions to do that...", ephemeral=True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.author_id == interaction.user.id:
            self.stop()
        else:
            await interaction.response.send_message("You do not have permissions to do that...", ephemeral=True)


class MemberConverter(commands.MemberConverter):
    bot: Optional[commands.Bot] = None

    async def convert(self, guild: discord.Guild, argument, mentions: list = None):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]{15,20})>$', argument)
        user_id = None
        if match is None:
            if guild:
                result = guild.get_member_named(argument)
            else:
                result = discord.ext.commands.converter._get_from_guilds(self.bot, "get_member_named", argument)
        else:
            user_id = int(match.group(1))
            if guild and mentions:
                result = guild.get_member(user_id) or discord.utils.get(mentions, id=user_id)
            else:
                result = discord.ext.commands.converter._get_from_guilds(self.bot, "get_member", user_id)

        if result is None:
            if guild is None:
                raise commands.MemberNotFound(argument)

            if user_id is not None:
                result = await self.query_member_by_id(self.bot, guild, user_id)
            else:
                result = await self.query_member_named(guild, argument)

            if not result:
                raise commands.MemberNotFound(argument)

        return result

class SelectionRow(discord.ui.Select):
    def __init__(self, modules: dict, author: discord.Member, config: Config, gm: Gamemode):
        self.config = config
        self.gamemode = gm
        self.author = author
        self.all_modules = modules
        self.modules = modules[author.guild.id][str(gm)]

        options = []
        for module in self.modules:
            options.append(discord.SelectOption(label=module.name, description=module.db_key))

        super().__init__(
            placeholder="Select the modules in the order you want...",
            options=options,
            min_values=len(self.modules),
            max_values=len(self.modules)
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.author:
            new_modules = []
            names = [module.name for module in self.modules]
            for v in self.values:
                idx = names.index(v)
                new_modules.append(self.modules[idx])

            self.all_modules[interaction.guild.id][str(self.gamemode)] = new_modules
            new_modules = [(module.db_key, module.name) for module in self.modules]

            await self.config.guild(interaction.guild).set_raw(
                str(self.gamemode), "current_modules", value=new_modules
            )

            await interaction.response.send_message("Order changed.")
            self.view.stop()
        else:
            await interaction.response.send_message(
                "Only the author of the original message can interact with this component.",
                ephemeral=True
            )


class Module:
    """Class representing a single module"""
    all_modules: Optional[dict] = None
    custom_modules: Optional[dict] = None

    def __init__(
            self,
            name: str,
            db_key: str = None,
            calc: str = None,
            gm: Gamemode = None,
    ):
        self._name: str = name
        self._db_key: Optional[str] = db_key
        self._calc: Optional[str] = calc
        self._gamemode: Optional[Gamemode] = gm

    @property
    def name(self):
        return self._name

    @property
    def db_key(self):
        return self._db_key

    @property
    def is_custom(self):
        return bool(self._calc)

    @property
    def calculation(self):
        return self._calc

    @property
    def gamemode(self):
        return self._gamemode

    def get_value(self, player: Optional[Any] = None, stats: Optional[dict] = None):
        stats = stats if not player else player.stats(self._gamemode)
        if not stats:
            return

        if not self.is_custom:
            return stats.get(self._db_key, 0)

        try:
            calc = re.sub("{}", f"{stats=}".split("=")[0], self._calc)
            return eval(calc)
        except KeyError:
            return 0


class Autostats:
    def __init__(self,
                 cog,
                 channel: discord.TextChannel,
                 gm: Gamemodes,
                 users: list,
                 ):
        self.channel: discord.TextChannel = channel
        self.gamemode: Gamemodes = gm
        self.users = users
        self.cog: Hypixel = cog
        self.messages: list = []

        self.last_updated: Optional[int] = None
        self.task: Optional[asyncio.Task] = None

    @staticmethod
    def _exception_catching_callback(task: asyncio.Task):
        if task.exception():
            task.result()

    def add_player(self, user: Player):
        if user not in self.users:
            self.users.append(user)

    async def remove_player(self, user: Player):
        if user in self.users:
            self.users.remove(user)

        if not self.users:
            await self.cancel()

    async def is_updated(self):
        user = self.users[0]
        prev = user.stats(self.gamemode)
        await user.fetch_stats()
        if user.stats(self.gamemode)[self.gamemode.autostats_key] != prev[self.gamemode.autostats_key]:
            return True

        return False

    def timeout(self):
        if time.time() > self.last_updated + 3600:
            return True
        return False

    async def main(self):
        try:
            while not self.task.cancelled():
                first_previous = self.users[0].stats(self.gamemode)
                if self.timeout():
                    await self.cancel()
                if await self.is_updated():
                    self.last_updated = int(time.time())
                    await self.maybe_delete_old_messages()
                    im_list = []

                    for user in self.users:
                        previous = user.stats(self.gamemode)
                        await user.fetch_stats()

                        im_list.append(await self.cog.create_stats_img(
                            player=user,
                            gm=self.gamemode,
                            compare_stats=first_previous if first_previous else previous
                        ))
                        first_previous = None

                    self.messages = await self.cog.maybe_send_images(self.channel, im_list)
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def maybe_delete_old_messages(self):
        try:
            await self.channel.delete_messages(messages=self.messages)
            self.messages = []
        except (discord.Forbidden, discord.NotFound):
            pass

    async def start(self):
        self.last_updated = int(time.time())
        im_list = await asyncio.gather(*[self.cog.create_stats_img(user, self.gamemode) for user in self.users])

        self.messages = await self.cog.maybe_send_images(self.channel, im_list)

        self.task = asyncio.create_task(self.main())
        self.task.add_done_callback(self._exception_catching_callback)

    async def cancel(self):
        await self.maybe_delete_old_messages()
        self.task.cancel()
        del self


class Hypixel(commands.Cog, MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=365911945565569036, force_registration=True)
        self.session = aiohttp.ClientSession()
        self.cog_ready_event = asyncio.Event()
        self.modules = {}

        Player.session = self.session
        Player.config = self.config
        Player.bot = self.bot

        MemberConverter.bot = self.bot

        self.autostats_tasks = {
            s.value: {} for s in Scope
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
        for gm in Gamemodes:
            if gm == Gamemodes.BEDWARS:  # default modules for bedwars
                gamemode_data[str(gm.value)] = {
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
                        "wl_rate": "round(({}['wins_bedwars'] / {}['losses_bedwars']), 2)",
                        "normal_kd": "round(({}['kills_bedwars'] / {}['deaths_bedwars']), 2)",
                        "final_kd": "round(({}['final_kills_bedwars'] / {}['final_deaths_bedwars']), 2)",
                    },
                }
            else: # no defaults present for the rest (mainly because i never played them)
                gamemode_data[str(gm.value)] = {
                    "current_modules": [],
                    "custom_modules": {},
                }

        default_guild = {
            "apikey": None,
            "minecraft_voice_channel": None,
            "minecraft_channel": None,
            "header_color": [255, 0, 0],
            "default_backgrounds": True,
            "default_fonts": True,
            **gamemode_data
        }

        self.config.register_global(**default_global)
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        bot.loop.create_task(self.initialize())

    async def initialize(self):
        self.cog_ready_event.clear()
        await self.bot.wait_until_red_ready()
        await self.bot.tree.sync()
        # data_path = cog_data_path(self)
        #
        # for path in bundled_data_path(self).iterdir():
        #     path = path.name
        #     if not (data_path / path).exists():
        #         (data_path / path).mkdir()
        #
        #     for file in (bundled_data_path(self) / path).iterdir():
        #         if file.is_file():
        #             try:
        #                 shutil.copy(str(file), str(data_path / path))
        #             except shutil.Error:
        #                 pass
        #     shutil.rmtree(str(bundled_data_path(self) / path))

        Module.all_modules = await self.fetch_modules()

        async for guild in AsyncIter(self.bot.guilds):
            guild_data = await self.config.guild(guild).all()
            self.modules[guild.id] = {}
            for gm in Gamemodes:
                self.modules[guild.id][str(gm.value)] = []
                active_modules = guild_data[str(gm.value)]["current_modules"]
                custom_modules = guild_data[str(gm.value)]["custom_modules"]

                for db_key, name in active_modules:
                    if db_key in custom_modules.keys():
                        self.modules[guild.id][str(gm.value)].append(
                            Module(
                                name=name,
                                db_key=db_key,
                                calc=custom_modules[db_key],
                                gm=gm.value,
                            )
                        )
                    else:
                        self.modules[guild.id][str(gm.value)].append(
                            Module(
                                name=name,
                                db_key=db_key,
                                gm=gm.value,
                            )
                        )

        self.cog_ready_event.set()


    """Listeners"""
    @commands.Cog.listener("on_voice_state_update")
    async def on_voice_state_update(self, member, before, after):
        """Comparing previous voice channel with current one
        starting/stopping autostats accordingly"""
        if after.channel != before.channel:
            vc = await self.config.guild(member.guild).minecraft_voice_channel()
            if not vc:
                return

            vc = await self.get_or_fetch_channel(vc)
            if not vc:
                return

            if vc == after.channel:
                user = Player(str(member.id), guild=member.guild)
                await user.wait_for_fully_constructed()
                if not user.valid:
                    return

                text_channel = await self.config.guild(member.guild).minecraft_channel()
                if not text_channel:
                    return

                text_channel = await self.get_or_fetch_channel(text_channel)
                if not text_channel:
                    return

                try:
                    task = self.autostats_tasks[vc.id]
                    task.add_player(user)
                except KeyError:
                    self.autostats_tasks[vc.id] = Autostats(
                        self,
                        text_channel,
                        Gamemodes.BEDWARS.value,
                        [user]
                    )
                    await self.autostats_tasks[vc.id].start()
            else:
                try:
                    task = self.autostats_tasks[vc.id]
                    for player in task.users:
                        if player._user == member:
                            await task.remove_player(player)
                            del self.autostats_tasks[vc.id]
                except KeyError:
                    """No running autostats tasks"""
                    pass

    """Dpy Events"""
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if self.command_hypixelset in [ctx.command, ctx.command.root_parent]:
            return

        user_key = await self.config.user(ctx.author).apikey()
        if not ctx.guild and not user_key:
            await ctx.send("No personal apikey set!")
            raise commands.CheckFailure()

        elif not user_key and not await self.config.guild(ctx.guild).apikey():
            await ctx.send("No personal or guild apikey set!\n"
                           f"Run `{ctx.clean_prefix}help hypixelset apikey` in DMs to learn more.")
            raise commands.CheckFailure()

        await self.cog_ready_event.wait()

    def cog_unload(self) -> None:
        asyncio.create_task(self.cog_unload_task())

    async def cog_unload_task(self) -> None:
        for s in Scope:
            for task in self.autostats_tasks[s.value].values():
                await task.cancel()

        for k, v in self.autostats_tasks.items():
            if isinstance(v, Autostats):
                await v.cancel()

        await self.session.close()

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord", "owner", "user", "user_strict"],
        user_id: int,
    ):
        await self.config.user_from_id(user_id).clear()


    """Image gen"""
    async def create_stats_img_new(self, player: Player, gm: Gamemode, modules: list):
        datapath: pathlib.Path = cog_data_path(self)
        background_paths: List[pathlib.Path] = [
            datapath / "backgrounds",
            bundled_data_path(self) / "backgrounds"
        ]

        # take care of the background image
        im_background = await self.fetch_background(background_paths)

        font_path = self.fetch_font([datapath / "fonts"], "Minecraft-Regular")

        draw = ImageDraw.Draw(im_background, "RGBA")

        # top box
        font = ImageFont.truetype(str(font_path), size=40)
        x_top = (im_background.width * 0.02, im_background.width * 0.98)
        y_top = (im_background.height * 0.02, im_background.height * 0.22)

        draw.rounded_rectangle([(x_top[0], y_top[0]), (x_top[1], y_top[1])], fill=(0, 0, 0, 120), radius=20)
        y_text = y_top[1] / 2 + y_top[0]
        x_text = x_top[0] + im_background.width * 0.02

        draw.text(
            (x_text, y_text),
            text=f"[{player.xp()[0]}✫]",
            font=font,
            anchor="lm",
            fill="#55FFFF"
        )
        x_text += font.getlength(f"[{player.xp()[0]}✫] ")

        if player.rank != Ranks.DEFAULT:
            pattern = re.compile("[+]")
            text = f"[{pattern.sub('', player.rank.value.clear_name)}"
            draw.text(
                (x_text, y_text),
                font=font,
                text=text,
                anchor="lm",
                fill=player.rank.value.color
            )
            x_text += font.getlength(text)

            for _ in range(0, len(pattern.findall(player.rank.value.clear_name))):
                draw.text(
                    (x_text, y_text),
                    font=font,
                    text="+",
                    anchor="lm",
                    fill=player.rank.value.plus_color
                )
                x_text += font.getlength("+")

            draw.text(
                (x_text, y_text),
                font=font,
                text=f"]",
                anchor="lm",
                fill=player.rank.value.color
            )
            x_text += font.getlength("]" + " ")

        draw.text(
            (x_text, y_text),
            font=font,
            text=player.name.upper(),
            anchor="lm",
            fill=player.rank.value.color,
        )

        # stats box
        font = ImageFont.truetype(str(font_path), size=20)
        x = (x_top[0], im_background.width * 0.7)
        y = (im_background.height * 0.25, im_background.height * 0.92)
        draw.rounded_rectangle([(x[0], y[0]), (x[1], y[1])], fill=(0, 0, 0, 120), radius=20)

        colors = [(0, 200, 0, 255), (200, 0, 0, 255), (255, 150, 200, 255), (0, 200, 200, 255)]

        start_x = (x[0] + im_background.width / 50)
        spacing_x = (x[1] - x[0]) / 3
        pos_x = start_x

        start_y = y[0] + im_background.width / 100
        spacing_y = (y[1] - y[0] - im_background.width / 20) / int(len(modules) / 3)
        pos_y = [start_y + spacing_y * x for x in range(int(len(modules) / 3))]

        for idx, module in enumerate(modules):
            if idx < (len(modules) / 3):
                color = colors[0] if (idx + 1) % int(len(modules) / 3) else colors[3]
            elif idx < (len(modules) / 3) * 2:
                pos_x = start_x + spacing_x
                color = colors[1] if (idx + 1) % int(len(modules) / 3) else colors[3]
            elif idx >= (len(modules) / 3) * 2:
                pos_x = start_x + spacing_x * 2
                color = colors[2] if (idx + 1) % int(len(modules) / 3) else colors[3]

            val = str(module.get_value(player))
            draw.text(
                (pos_x, pos_y[idx % int(len(modules) / 3)]),
                text=val,
                font=font,
                anchor="lt",
                fill=color,
            )
            draw.text(
                (pos_x + font.getlength(val + " "), pos_y[idx % int(len(modules) / 3)]),
                text=module.name,
                font=font,
                anchor="lt",
            )

        # skin box
        x_skin = (im_background.width * 0.72, x_top[1])
        draw.rounded_rectangle([(x_skin[0], y[0]), (x_skin[1], y[1])], fill=(0, 0, 0, 120), radius=20)

        pos = random.choice([
            (-25, -25, 20, 5, -2, -20, 2),
            (-25, 25, 20, 5, -2, 20, -2),
            (-5, 25, 10, 5, -2, 5, -5),
            (-5, -25, 10, 5, -2, -5, 5),
            (0, 0, 0, 0, 0, 0, 0),
        ])
        im_skin = await MinePI.render_3d_skin(
            player.uuid,
            *pos,
            12,
            True,
            True,
            False,
            skin_image=player.skin
        )

        height = y[1] - y[0] - im_background.height / 25
        width = im_skin.width * (height / im_skin.height)
        im_skin = im_skin.resize((int(width), int(height)))

        x_pos_skin = int((x_skin[0] + (x_skin[1] - x_skin[0]) / 2) - im_skin.width / 2)
        y_pos_skin = int((y[0] + (y[1] - y[0]) / 2) - im_skin.height / 2)
        im_background = im_background.convert("RGBA")
        im_background.alpha_composite(im_skin, (x_pos_skin, y_pos_skin))

        im_xp = self.render_xp_bar_new(player, int(x[1] - x[0]))
        im_background.alpha_composite(
            im_xp, (int(x[0] + im_background.width / 50), int(y[1] - im_xp.height - im_background.height / 100))
        )

        return im_background

    async def create_stats_img(self, player: Player, gm: Gamemode, compare_stats: list = None) -> Image.Image:
        datapath: pathlib.Path = cog_data_path(self)
        background_paths: List[pathlib.Path] = [
            datapath / "backgrounds",
            bundled_data_path(self) / "backgrounds"
        ]

        color_header_stats = (255, 145, 0)
        color_body_stats = (255, 200, 0)

        # take care of the background image
        im_background = await self.fetch_background(background_paths)

        pos = random.choice([
            (-25, -25, 20, 5, -2, -20, 2),
            (-25, 25, 20, 5, -2, 20, -2),
            (-5, 25, 10, 5, -2, 5, -5),
            (-5, -25, 10, 5, -2, -5, 5),
            (0, 0, 0, 0, 0, 0, 0),
        ])
        im_skin = await MinePI.render_3d_skin(
            player.uuid,
            *pos,
            12,
            True,
            True,
            False,
            skin_image=player.skin
        )

        modules = self.modules[player._guild.id][str(gm)]
        def generate_image(im_skin):
            # fetch available fonts
            font_header_player_path = self.fetch_font([datapath / "fonts"], "header_player")
            font_header_stats_path = self.fetch_font([datapath / "fonts"], "header_stats")
            font_body_stats_path = self.fetch_font([datapath / "fonts"], "body_stats")

            font_header_player = ImageFont.truetype(str(font_header_player_path), int(im_background.height / 6.5))
            font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(im_background.height / 8))

            modules_left = int(len(modules) / 2 + 1) if len(modules) % 2 else int(len(modules) / 2)

            height = int(im_background.height / 1.4)
            width = int(height * (im_skin.width / im_skin.height))
            im_skin = im_skin.resize((width, height), resample=Image.BOX)

            if len(modules) > 5:
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

            draw.text(
                ((im_background.width / 2), im_background.height / 100),
                player.name,
                fill=player.rank.value.color,
                font=font_header_player,
                anchor="mt"
            )

            if modules_left:
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

                longest_item = max([x.name for x in modules], key=len)
                length = font_header_stats.getlength(longest_item)
                if length > stats_box[0]:
                    font_size = font_header_stats.size * (stats_box[0] / length)
                    del font_header_stats
                    font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(font_size))

                font_body_stats = ImageFont.truetype(str(font_body_stats_path), int(font_header_stats.size * 0.95))

                anchor = "lm"
                compare_anchor = "rm"
                x = int(im_background.width / 25)
                compare_x = stats_box[0]
                header_margin = int(font_header_player.size + im_background.height / 100)
                for i, module in enumerate(modules):
                    try:
                        y = y_pos[i] + header_margin
                    except IndexError:
                        y = y_pos[i - modules_left] + header_margin

                    if i == modules_left:
                        anchor = "rm"
                        compare_anchor = "lm"
                        # compare_x = (im_background.width - stats_box[0]) + x + im_skin.width / 2
                        compare_x = stats_box[0] + im_skin.width * 1.5 + x
                        # print(stats_box[0], im_background.width, im_skin.width, x, compare_x)
                        # print(im_background.width - im_skin.width)
                        x = int(im_background.width * 0.96)

                    draw.text(
                        (x, y),
                        module.name,
                        fill=color_header_stats,
                        font=font_header_stats,
                        anchor=anchor
                    )

                    draw.text(
                        (x, y + font_header_stats.size * 0.9),
                        str(module.get_value(player)),
                        fill=color_body_stats,
                        font=font_body_stats,
                        anchor=anchor
                    )

                    if compare_stats:
                        compare_value, compare_color = self.get_compare_value_and_color(
                            module,
                            module.get_value(player),
                            compare_stats,
                        )

                        draw.text(
                            (compare_x, y + font_header_stats.size * 0.9),
                            compare_value,
                            fill=compare_color,
                            font=font_body_stats,
                            anchor=compare_anchor
                        )

            if gm.xp_key:
                xp_bar_im = self.render_xp_bar(gm, player, im_background.size)
                im_background.alpha_composite(xp_bar_im, (0, 0))

        await self.bot.loop.run_in_executor(
            None,
            generate_image,
            im_skin
        )

        return im_background

    async def fetch_background(self, paths: List[pathlib.Path]) -> Image.Image:
        def prepare_background_im():
            files = []
            for path in paths:
                files.extend([file for file in path.iterdir() if file.is_file()])
            im_background = Image.open(random.choice(files)).convert("RGBA")
            im_background = ImageEnhance.Brightness(im_background).enhance(0.3)
            im_background = im_background.filter(ImageFilter.GaussianBlur(im_background.width / 300))
            return im_background

        return await self.bot.loop.run_in_executor(
            None,
            prepare_background_im
        )

    def fetch_font(self, paths: List[pathlib.Path], query: str) -> pathlib.Path:
        for path in paths:
            for file in path.iterdir():
                if file.is_file() and query in file.stem:
                    return file
        else:
            raise ValueError(f"Font {query} not found.")

    def get_compare_value_and_color(
            self,
            module: Module,
            new_val: Optional[Union[int, float, str]],
            c_stats: dict
    ) -> Tuple[Any, Optional[Tuple]]:
        try:
            float(new_val)
        except ValueError:
            return new_val, None

        green = (0, 255, 0)
        red = (255, 0, 0)
        negative_list = [
            "loss"
        ]
        compare = new_val - module.get_value(stats=c_stats)
        compare = int(compare) if compare % 1 == 0 else round(compare, 2)

        if compare == 0:
            return str(compare), None

        elif compare < 0:
            for i in negative_list:
                if (module.db_key if not module.is_custom else module.name) in i:
                    return str(compare), green
            return str(compare), red

        else:
            for i in negative_list:
                if (module.db_key if not module.is_custom else module.name) in i:
                    return str(compare), red
            return str(compare), green

    def render_xp_bar_new(self, player, width) -> Image.Image:
        im = Image.new("RGBA", (width, 30))
        draw = ImageDraw.Draw(im)

        bar_color = "#AAAAAA"
        line_color = "#55FFFF"

        const = 15
        y = 10

        level, xp, xp_for_next_level = player.xp(Gamemodes.BEDWARS.value)
        xp = int(round(xp * xp_for_next_level, 0))

        font_path = self.fetch_font([cog_data_path(self) / "fonts"], "Minecraft-Regular")
        xp_font = ImageFont.truetype(str(font_path), size=const * 2)

        spacing = const
        text = f"[{level}✫] "
        draw.text(
            (spacing, y + 1),
            text=text,
            font=xp_font,
            anchor="lm",
            fill=line_color,
        )
        spacing += xp_font.getlength(text)

        draw.text(
            (spacing + const, y + 1),
            text="[",
            font=xp_font,
            anchor="rm",
        )
        spacing += xp_font.getlength("[") + int(const * 0.5)

        for i in range(1, 11):
            color = line_color if xp * (0.002 / i) >= 1 else bar_color
            draw.line(
                ((spacing, y), (spacing + const, y)),
                fill=color,
                width=const,
            )
            spacing += int(const * 1.5)

        draw.text(
            (spacing, y + 1),
            text="]",
            font=xp_font,
            anchor="lm",
        )
        spacing += xp_font.getlength("]")

        text = f" [{level + 1}✫]"
        draw.text(
            (spacing, y + 1),
            text=text,
            font=xp_font,
            anchor="lm",
            fill=line_color,
        )
        spacing += xp_font.getlength(text)

        # draw.text(
        #     (spacing + int(const * 11 * 2), y + 1),
        #     text=f"[{xp} / {xp_for_next_level}]",
        #     font=xp_font,
        #     anchor="lm"
        # )

        return im

    def render_xp_bar(self, gm: Gamemode, player, size: tuple):
        level, percentage, _ = player.xp(gm)
        im = Image.new("RGBA", size)
        draw = ImageDraw.Draw(im)

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
        font_xp_path = self.fetch_font([cog_data_path(self) / "fonts"], "xp")
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

        all_modules = {}
        for gm, modules in resp["player"]["stats"].items():
            all_modules[gm] = [x for x in modules.keys() if isinstance(x, str) or isinstance(x, int)]

        return all_modules

    async def get_or_fetch_channel(self, channel_id: int) -> Union[discord.VoiceChannel, discord.TextChannel]:
        """returns a channel by the given id

        First checks the cache, then querries the api
        """
        channel = self.bot.get_channel(channel_id)
        if not channel:
            channel = self.bot.fetch_channel(channel_id)
        return channel

    async def maybe_send_images(self, channel: discord.TextChannel, im_list: List[Image.Image]) -> List[discord.Message]:
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
                messages.append(
                    await channel.send(
                        "Looks like i do not have the proper permission to send attachments to this channel"
                    )
                )

        return messages

    async def send_failed_for(self, ctx: commands.Context, users: List):
        if len(users) == 1:
            if users[0]._user:
                msg = (f"Fetching stats for `{users[0]._user.name}` failed. Looks like the given discord user doesn't "
                       f"have a minecraft name set yet. Tell them do to so by running "
                       f"`{ctx.clean_prefix}hypixelset username`.")
            else:
                msg = f"Fetching stats for `{users[0]._user_identifier}` failed. "
                if users[0]._resp is None:
                    msg += "Retrieving data from the hypixel api failed."
                else:
                    msg += "Looks like this player never joined hypixel."
        else:
            msg = "Fetching stats for the following users failed: \n"

            failed = []
            for user in users:
                if user._user:
                    failed.append([user._user.name, "No MC name set"])
                else:
                    if not user.uuid:
                        reason = "Invalid MC name"
                    elif user._resp is None:
                        reason = "Request failed. API might be down"
                    else:
                        reason = "Never joined hypixel"

                    failed.append([f"{user._user_identifier}:", f"- {reason}"])

            msg += f"```yaml\n{tabulate.tabulate(failed, ['user', 'reason'])}\n```"

        await ctx.send(msg)

