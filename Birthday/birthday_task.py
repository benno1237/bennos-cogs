from redbot.core import commands
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import pagify

from typing import Optional

import contextlib
import discord
import datetime
import pytz
import asyncio


def done_callback(task):
    if task.done():
        task.result()


class Tasks:
    def __init__(self):
        self.time_for_guild_loops: dict = {}
        self.reset: asyncio.Event = asyncio.Event()
        self.task_main: Optional[asyncio.Task] = None

    def start(self):
        if self.is_running():
            self.stop()
               
        self.task_main: asyncio.Task = self.bot.loop.create_task(self.task_main())
        self.task_main.add_done_callback(done_callback)

    def stop(self):
        with contextlib.suppress(asyncio.CancelledError):
            self.task_main.cancel()

    def is_running(self):
        if not self.task_main:
            return False

        if isinstance(self.task_main, asyncio.Task):
            return not self.task_main.cancelled()

    async def initialize_guild_loops(self):
        self.time_for_guild_loops = {}
        async for guild in AsyncIter(self.bot.guilds):
            await self.update_time_for_guild(guild)

    async def update_time_for_guild(self, guild: discord.Guild, timestamp=None):
        timezone = await self.config.guild(guild).timezone()
        now = datetime.datetime.now(pytz.timezone(timezone))

        utc_time_for_guild_loop: datetime.datetime = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time(hour=0)) - now.utcoffset()

        self.time_for_guild_loops[guild.id] = utc_time_for_guild_loop.timestamp() if not timestamp else timestamp

    async def wait_task(self, time: float):
        await asyncio.sleep(
            time - datetime.datetime.utcnow().timestamp()
        )

    async def task_main(self):
        try:
            await self.bot.wait_until_red_ready()
            await self.initialize_guild_loops()
            while True:
                next_loop = sorted(list(self.time_for_guild_loops.items()), key=lambda i: i[1])[0]

                guild = self.bot.get_guild(next_loop[0])

                wait = asyncio.create_task(self.wait_task(next_loop[1]))

                await asyncio.wait(
                    [
                        self.reset.wait(),
                        wait
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self.reset.is_set():
                    wait.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await wait
                        self.reset.clear()

                await self.update_time_for_guild(guild)

                guild_data = await self.config.guild(guild).all()
                channel = guild.get_channel(guild_data["channel"])
                role = guild.get_role(guild_data["role"])

                if channel:
                    bdays = await self.get_bdays(guild)

                    msg = ""
                    async for bday in AsyncIter(bdays):
                        now = datetime.datetime.now(pytz.timezone(guild_data["timezone"]))
                        month = now.month
                        day = now.day

                        if (int(bday[1]) == int(day)) and (int(bday[2]) == int(month)):
                            bday_msg = await self.get_custom_message(bday[0])
                            msg += bday_msg + "\n\n"

                            if role:
                                async for member in AsyncIter(role.members):
                                    member: discord.Member
                                    await member.remove_roles(role, reason="Birthday is over")

                                async for bday in AsyncIter(bdays):
                                    if isinstance(bday[0], discord.Member):
                                        await bday[0].add_roles(role, reason="Birthday")

                    if msg != "":
                        pages = list(pagify(msg, delims=["\n\n"], page_length=1000))
                        for page in pages:
                            embed = discord.Embed(color=discord.Color.blue(), description=page)
                            await channel.send(embed=embed)

        except asyncio.CancelledError:
            raise

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.update_time_for_guild(guild)
        if not self.reset.is_set():
            self.reset.set()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        if guild.id in self.time_for_guild_loops.keys():
            del self.time_for_guild_loops[guild.id]
            if not self.reset.is_set():
                self.reset.set()

    def cog_unload(self):
        self.stop()
