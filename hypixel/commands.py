

class Commands:
    @commands.guild_only()
    @commands.group(name="autostats", invoke_without_command=True)
    async def command_autostats(self, ctx: commands.Context, gm: Gamemodes, *usernames: str) -> None:
        """Automatically sends your stats

        Automatically updates the stats image sent to discord after each round
        This is still a heavy WIP. Since hypixel only updates their api as soon
        as a game ends, stats can sometimes be messed up

        **Args**:
            **gm**: The gamemode you want to get stats for
            **usernames**: a single or multiple discord Members or minecraft names

        Example use:
            `[p]autostats bedwars`
            `[p]autostats bedwars Technoblade sucr_kolli`
        """
        if gm not in [gm.value for gm in Gamemodes if gm.value.autostats_key]:
            await ctx.send("The given gamemode currently isn't supported for autostats")
            return

        async with ctx.typing():
            usernames = usernames if usernames else [ctx.author]
            users = [Player(user_identifier, ctx=ctx) for user_identifier in usernames]
            await asyncio.gather(*[user.wait_for_fully_constructed() for user in users])

            _, key_scope = await Player.fetch_apikey(ctx=ctx)

            if key_scope == Scope.GUILD:
                if len(self.autostats_tasks[key_scope.value]) >= 5:
                    await ctx.send("Already 5 autostats tasks running on the guild apikey. "
                                   f"Set your own apikey using `{ctx.clean_prefix}hypixelset apikey`")
                    return

            if all([user.valid for user in users]):
                autostats_task = Autostats(
                    self,
                    ctx.channel,
                    gm,
                    users,
                )

                self.autostats_tasks[key_scope.value][ctx.author.id] = autostats_task
                await autostats_task.start()
            else:
                failed = []
                for user in users:
                    if not user.valid:
                        failed.append(user)
                await self.send_failed_for(ctx, failed)


    @command_autostats.group(name="stop", invoke_without_command=True)
    async def command_autostats_stop(self, ctx: commands.Context) -> None:
        """Stops your current autostats process"""
        for s in Scope:
            if ctx.author.id in self.autostats_tasks[s.value].keys():
                await self.autostats_tasks[s.value][ctx.author.id].cancel()
                del self.autostats_tasks[s.value][ctx.author.id]
                await ctx.tick()
                return

        await ctx.send("No running autostats tasks")


    @command_autostats_stop.command(name="all")
    async def command_autostats_stop_all(self, ctx: commands.Context, stop_scope: Scope = True) -> None:
        """Stops all autostats processes"""
        if self.bot.is_owner(ctx.author) or ctx.guild.owner == ctx.author:
            if stop_scope == Scope.GUILD:
                for task in self.autostats_tasks[stop_scope.value].values():
                    await task.cancel()

        if self.bot.is_owner(ctx.author):
            for task in self.autostats_tasks[stop_scope.value].values():
                await task.cancel()


    @commands.command(name="gamemodes")
    async def command_gamemodes(self, ctx) -> None:
        """Lists all available gamemodes"""
        await ctx.maybe_send_embed("\n".join([gm.value.db_key for gm in Gamemodes]))


    @commands.group(name="hypixelset")
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        """Base command for cog settings"""
        pass


    @commands.dm_only()
    @command_hypixelset.command(name="apikey")
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, *, guild: discord.Guild = None) -> None:
        """Api key management for the hypixel api

        Keys are managed server wide and on a user basis
        If `guild` is given, the key is set for the whole guild
        else the key is treated as a personal one and only used for you

        Api keys can be obtained by typing `/api` on the hypixel minecraft server

        **Arguments**:
            **apikey**: your hypixel api key
            **guild**: guild to set the apikey for

        Example use:
            `[p]hypixelset apikey <your_key>`
            `[p]hypixelset apikey <your_key> 133049272517001216`
        """
        resp, status = await Player.request_hypixel(topic="key", apikey=apikey)

        if status == 200 and resp:
            if not guild:
                await self.config.user(ctx.author).apikey.set(apikey)
                await ctx.tick()
            else:
                member = guild.get_member(ctx.author)
                if member or await self.bot.is_owner(ctx.author):
                    if await self.bot.is_owner(ctx.author) or member.guild_permissions.manage_guild:
                        await self.config.guild(guild).apikey.set(apikey)
                        await ctx.tick()
                    else:
                        await ctx.send("Sorry, looks like you do not have proper permissions to set an apikey "
                                       f"for the guild {guild.name}. Ask a server moderator to do so.")
                else:
                    await ctx.send(f"You do not appear to be a member of {guild.name}")

        elif status == 403 and resp["cause"] == INVALID_API_KEY:
            await ctx.send("This apikey doesn't seem to be valid!")


    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.group(name="autostats")
    async def command_hypixelset_autostats(self, ctx: commands.Context) -> None:
        """Autostats management"""


    @command_hypixelset_autostats.command(name="channel")
    async def command_hypixelset_autostats_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Channel to send the autostats images to

        Only required if an autostats voicechannel is set
        """
        await self.config.guild(ctx.guild).minecraft_channel.set(channel.id)
        await ctx.send(f"Autostats channel set to {channel.mention}")


    @command_hypixelset_autostats.command(name="info")
    async def command_hypixelset_autostats_info(self, ctx: commands.Context) -> None:
        """Info command for autostats

        *Channel*: settable using `[p]hypixelset autostats channel`
        The channel to send the stats to
        """


    @command_hypixelset_autostats.command(name="voicechannel")
    async def command_hypixelset_autostats_voicechannel(self, ctx: commands.Context,
                                                        channel: discord.VoiceChannel = None) -> None:
        """Voice channel for autostats task

        Stats of the players connected to this channel will be automatically pushed
        to the channel set voice `[p]hypixelset autostats channel`
        This is required for this feature to work

        This feature only works if the newly connected user has his minecraft name set

        Leave blank to disable this feature
        """
        if channel:
            await self.config.guild(ctx.guild).minecraft_voice_channel.set(channel.id)
            await ctx.send(f"{channel.mention} will now be used to automatically start autostats sessions.")
        else:
            await self.config.guild(ctx.guild).minecraft_voice_channel.set(None)
            await ctx.send("Autostats disabled.")


    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.command(name="defaultbackgrounds")
    async def command_hypixelset_defaultbackgrounds(self, ctx: commands.Context) -> None:
        """Toggles whether or not default backgrounds are used for the rendered images"""
        current_state = await self.config.guild(ctx.guild).default_backgrounds()
        await self.config.guild(ctx.guild).default_backgrounds.set(not current_state)

        if current_state:
            await ctx.send("Default backgrounds will from now on not be used anymore.\n"
                           f"Custom backgrounds can be added to {str(cog_data_path(self) / 'backgrounds')}")
        else:
            await ctx.send("Default backgrounds will now be used.")


    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.command(name="defaultfonts")
    async def command_hypixelset_defaultfonts(self, ctx: commands.Context) -> None:
        """Toggles whether or not default backgrounds are used for the rendered images"""
        current_state = await self.config.guild(ctx.guild).default_backgrounds()
        await self.config.guild(ctx.guild).default_backgrounds.set(not current_state)

        if current_state:
            await ctx.send("Default fonts will from now on not be used anymore.\n"
                           f"Custom backgrounds can be added to {str(cog_data_path(self) / 'fonts')}")
        else:
            await ctx.send("Default fonts will now be used.")


    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.group(name="modules", aliases=["module"])
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        """Base command for managing modules"""
        pass


    @command_hypixelset_modules.command(name="add")
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gm: Gamemodes, db_key: str, *,
                                             clear_name: str) -> None:
        """Add a module for the given gamemode"""
        guild_data = await self.config.guild(ctx.guild).get_raw(str(gm))

        custom_modules = guild_data["custom_modules"]

        modules = self.modules[ctx.guild.id][str(gm)]
        if not (db_key in Module.all_modules[str(gm)] or db_key in custom_modules.keys()):
            await ctx.send(f"The given database key (`{db_key}`) doesn't seem to be a "
                           f"valid default nor custom one. You can list all available ones by typing "
                           f"`{ctx.clean_prefix}hypixelset modules list {gm.db_key}` first.")
            return

        if db_key in [module.db_key for module in modules]:
            await ctx.send(f"The given database key (`{db_key}`) is already added. Remove it by typing "
                           f"`{ctx.clean_prefix}hypixelset modules remove {db_key}` first.")
            return

        if clear_name in [module.name for module in modules]:
            await ctx.send(f"The given module name (`{clear_name}`) is already added. Remove it by typing "
                           f"`{ctx.clean_prefix}hypixelset modules remove {clear_name}` first.")
            return

        self.modules[ctx.guild.id][str(gm)].append(
            Module(
                name=clear_name,
                db_key=db_key,
                calc=custom_modules[db_key] if db_key in custom_modules.keys() else None,
                gm=gm,
            )
        )
        guild_data["current_modules"].append((db_key, clear_name))
        await self.config.guild(ctx.guild).set_raw(
            str(gm), "current_modules", value=guild_data["current_modules"]
        )

        await ctx.tick()


    @command_hypixelset_modules.command(name="create")
    async def command_hypixelset_modules_create(self, ctx: commands.Context, gm: Gamemodes, db_key: str, *,
                                                calc: str) -> None:
        """Create a new custom module for the given gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")
        all_modules = Module.all_modules[gm.db_key] + list(custom_modules.keys())

        if db_key in all_modules:
            await ctx.send("The given db_key seems to be in use already.")
            return

        for module in Module.all_modules[gm.db_key]:
            print(module)
            pattern = re.compile(f"[{module}]")
            calc = pattern.sub(f"{{}}['{module}']", calc)

        print(calc)


    @command_hypixelset_modules.command(name="list")
    async def command_hypixelset_modules_list(self, ctx: commands.Context, *, gm: Gamemodes) -> None:
        """List all modules of a gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")

        modules_gamemode = Module.all_modules[gm.db_key] + list(custom_modules.keys())
        modules_gamemode = "\n".join(list(map(str, modules_gamemode)))

        await ctx.send(file=discord.File(BytesIO(modules_gamemode.encode()), "modules.txt"))


    @command_hypixelset_modules.command(name="remove")
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gm: Gamemodes, db_key: str = None, *,
                                                clear_name: str = None) -> None:
        """Remove a module for the given gamemode"""
        if not db_key and not clear_name:
            await ctx.send_help()
            return

        current_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")
        modules = self.modules[ctx.guild.id][str(gm)]

        for idx, module in enumerate(modules):
            if db_key == module.db_key or clear_name == module.name:
                self.modules[ctx.guild.id][str(gm)].pop(idx)
                current_modules.pop(idx)
                await self.config.guild(ctx.guild).set_raw(
                    str(gm), "current_modules", value=current_modules
                )
                await ctx.tick()
                return
        else:
            await ctx.send("No matching module found. You can list all modules by typing "
                           f"`{ctx.clean_prefix}hypixelset modules list {gm.db_key}`")


    @command_hypixelset_modules.command(name="reorder")
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, *, gm: Gamemodes) -> None:
        """Reorder modules"""
        view = discord.ui.View()
        view.add_item(SelectionRow(self.modules, ctx.author, self.config, gm))

        await ctx.send("Select the modules in your preferred order: ", view=view)


    @commands.guild_only()
    @command_hypixelset.command(name="username", aliases=["name"])
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        """Bind your minecraft account to your discord account

        Why this is useful? You UUID is stored. Thus people can mention you
        to see your stats. Passing discord members instead of minecraft usernames
        spares one request and thus speeds all other commands up

        **Args**:
            **username**: Your minecraft username

        Example Use:
            `[p]hypixelset username sucr_kolli`

        Example how it can be used afterwards:
            Bedwars stats without specifying a username:
            `[p]stats bedwars`
            Bedwars stats for Benno if he bound an MC account already:
            `[p]stats bedwars @Benno`
        """

        async with ctx.typing():
            resp, status = await Player.request_mojang(username)
            if status == 200 and resp.get("id", None):
                embed = discord.Embed(
                    color=await ctx.embed_color(), title="Is that you?"
                )
                skin = await MinePI.render_3d_skin(resp["id"], ratio=8)
                embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
                embed.add_field(name="Name", value=username, inline=False)
                embed.add_field(name="UUID", value=resp["id"], inline=False)
                embed.set_footer(text="Hypixel stats bot")
                embed.set_thumbnail(url=f"attachment://skin_{ctx.author.name}.png")

                with BytesIO() as imb:
                    skin.save(imb, "PNG")
                    imb.seek(0)
                    file = discord.File(imb, f"skin_{ctx.author.name}.png")

                view = ButtonConfirm(ctx.author.id)

                msg = await ctx.send(embed=embed, file=file, view=view)

                await view.wait()
                await msg.edit(view=None)
                if view.confirm:
                    await self.config.user(ctx.author).uuid.set(resp["id"])
                    await ctx.send("Username successfully set!")
                else:
                    await ctx.send("Cancelled")
            else:
                await ctx.send("The given username doesn't seem to be valid.")


    @commands.guild_only()
    @commands.hybrid_command(name="stats", description="Shows stats for the given gamemode")
    async def command_stats(self, ctx, gm: Gamemodes, usernames: Optional[str] = None) -> None:
        """Stats for the given gamemode

        Get a players stats for a hypixel gamemode

        **Args**:
            **gm**: The gamemode you want to get stats for
            **usernames**: a single or multiple discord Members or minecraft names

        Example use:
            `[p]stats bedwars`
            `[p]stats bedwars Technoblade sucr_kolli`
        """
        if usernames is None:
            usernames = [ctx.author]
        else:
            usernames = usernames.split(" ")

        async with ctx.typing():
            users = []
            for username in usernames:
                users.append(Player(username, ctx=ctx))

            await asyncio.gather(*[user.wait_for_fully_constructed() for user in users])
            im_list = []
            failed = []
            for user in users:
                if not user.valid:
                    failed.append(user)
                else:
                    im_list.append(await self.create_stats_img(user, gm))

            await self.maybe_send_images(ctx.channel, im_list)

        if failed:
            await self.send_failed_for(ctx, failed)


    @commands.command(name="tstats")
    async def command_tstats(self, ctx, user: str = None):
        active_modules = [
            ("wins_bedwars", "Wins"),
            ("kills_bedwars", "Kills"),
            ("final_kills_bedwars", "Final Kills"),
            ("beds_broken_bedwars", "Beds Broken"),
            ("kills_per_game", "Kills/Game"),
            ("losses_bedwars", "Losses"),
            ("deaths_bedwars", "Deaths"),
            ("final_deaths_bedwars", "Final Deaths"),
            ("beds_lost_bedwars", "Beds Lost"),
            ("final_kills_per_game", "Finals/Game"),
            ("win_loose_rate", "WLR"),
            ("kill_death_rate", "KDR"),
            ("final_kill_death_rate", "FKDR"),
            ("beds_broken_lost_rate", "BBLR"),
            ("beds_per_game", "Beds/Game"),
        ]

        custom_modules = {
            "kills_per_game": "round({}['kills_bedwars'] / {}['games_played_bedwars'], 2)",
            "final_kills_per_game": "round({}['final_kills_bedwars'] / {}['games_played_bedwars'], 2)",
            "win_loose_rate": "round({}['games_played_bedwars'] / {}['wins_bedwars'], 2)",
            "kill_death_rate": "round({}['kills_bedwars'] / {}['deaths_bedwars'], 2)",
            "final_kill_death_rate": "round({}['final_kills_bedwars'] / {}['final_deaths_bedwars'], 2)",
            "beds_broken_lost_rate": "round({}['beds_broken_bedwars'] / {}['beds_lost_bedwars'], 2)",
            "beds_per_game": "round({}['beds_broken_bedwars'] / {}['games_played_bedwars'], 2)",
        }

        modules = []
        for module in active_modules:
            if module[0] in custom_modules.keys():
                modules.append(
                    Module(
                        module[1],
                        module[0],
                        calc=custom_modules[module[0]],
                        gm=Gamemodes.BEDWARS.value,
                    )
                )
            else:
                modules.append(
                    Module(
                        module[1],
                        db_key=module[0],
                        gm=Gamemodes.BEDWARS.value,
                    )
                )

        async with ctx.typing():
            user = Player(
                user if user else ctx.author,
                ctx=ctx
            )

            await user.wait_for_fully_constructed()
            if user.valid:
                im = await self.create_stats_img_new(user, gm=Gamemodes.BEDWARS.value, modules=modules)
                await self.maybe_send_images(ctx.channel, [im])
            else:
                await self.send_failed_for(ctx, [user])