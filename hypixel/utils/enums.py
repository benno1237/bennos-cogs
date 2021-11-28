from redbot.core import commands
from typing import Optional
import enum

class Gamemode:
    def __init__(
            self,
            id: int,
            type_name: str,
            db_key: str,
            clean_name: str = None,
            xp_key: str = None
    ):
        self._id = id
        self._type_name = type_name
        self._db_key = db_key
        self._clean_name = clean_name if clean_name else db_key
        self._xp_key = xp_key

    def __str__(self):
        return self.db_key

    def __repr__(self):
        return f"gamemodes.{self.type_name}: ID: {self.id}, DB_KEY: {self.db_key}, NAME: {self.clean_name}"

    @property
    def id(self):
        return self._id

    @property
    def type_name(self):
        return self._type_name

    @property
    def db_key(self):
        return self._db_key

    @property
    def clean_name(self):
        return self._clean_name

    @property
    def xp_key(self):
        return self._xp_key


class Gamemodes(enum.Enum):
    ARCADE = Gamemode(
        14, "ARCADE", "Arcade"
    )
    ARENA = Gamemode(
        17, "ARENA", "Arena"
    )
    BATTLEGROUND = Gamemode(
        23, "BATTLEGROUND", "Battleground", "Warlords"
    )
    BEDWARS = Gamemode(
        58, "BEDWARS", "Bedwars", "Bed Wars", "Experience"
    )
    BUILD_BATTLE = Gamemode(
        60, "BUILD_BATTLE", "BuildBattle", "Build Battle"
    )
    DUELS = Gamemode(
        61, "DUELS", "Duels"
    )
    GINGERBREAD = Gamemode(
        25, "GINGERBREAD", "GingerBread", "Turbo Kart Racers"
    )
    SURVIVAL_GAMES = Gamemode(
        5, "SURVIVAL_GAMES", "HungerGames", "Blitz Survival Games"
    )
    MCGO = Gamemode(
        21, "MCGO", "MCGO", "Cops and Crims"
    )
    MURDER_MYSTERY = Gamemode(
        59, "MURDER_MYSTERY", "MurderMystery", "Murder Mystery"
    )
    PAINTBALL = Gamemode(
        4, "PAINTBALL", "Paintball"
    )
    QUAKECRAFT = Gamemode(
        2, "QUAKECRAFT", "Quake"
    )
    SKYWARS = Gamemode(
        51, "SKYWARS", "SkyWars", "SkyWars", "skywars_experience"
    )
    SKYCLASH = Gamemode(
        55, "SKYCLASH", "SkyClash"
    )
    SPEED_UHC = Gamemode(
        54, "SPEED_UHC", "SpeedUHC", "Speed UHC"
    )
    SUPER_SMASH = Gamemode(
        24, "SUPER_SMASH", "SuperSmash", "Smash Heroes"
    )
    TNTGAMES = Gamemode(
        6, "TNTGAMES", "TNTGames", "TNT Games"
    )
    TRUECOMBAT = Gamemode(
        52, "TRUECOMBAT", "TrueCombat", "Crazy Walls"
    )
    UHC = Gamemode(
        20, "UHC", "UHC", "UHC Champions"
    )
    VAMPIREZ = Gamemode(
        7, "VAMPIREZ", "VampireZ"
    )
    WALLS = Gamemode(
        3, "WALLS", "Walls"
    )
    WALLS3 = Gamemode(
        13, "WALLS3", "Walls3", "Mega Walls"
    )

    @classmethod
    async def convert(cls, ctx, argument) -> Optional[Gamemode]:
        for gm in Gamemodes:
            gm = gm.value
            if argument.lower() == gm.type_name.lower():
                return gm
            elif argument.lower() == gm.db_key.lower():
                return gm
            elif argument.lower() == gm.clean_name.lower():
                return gm
            else:
                try:
                    val = int(argument)
                    if val == gm.id:
                        return gm
                except ValueError:
                    pass

        await ctx.send_help()
        raise commands.CheckFailure()


class Scope(enum.Enum):
    GLOBAL = "global"
    GUILD = "guild"
    USER = "user"


class ColorTypes(enum.Enum):
    HSB = "hsb"
    HSL = "hsl"
    HSV = "hsv"
    RGB = "rgb"


class Rank:
    def __init__(
            self,
            db_key: str,
            clear_name: str,
            color: str = None,
            bracket_color: str = None,
            plus_color: str = None,
    ):
        self.db_key = db_key
        self.clear_name = clear_name
        self.color = color
        self.bracket_color = bracket_color
        self.plus_color = plus_color


class Ranks(enum.Enum):
    DEFAULT = Rank("NORMAL", "", color="#555555")
    VIP = Rank("VIP", "VIP", color="#55FF55")
    VIP_PLUS = Rank("VIP_PLUS", "VIP+", color="#55FF55", plus_color="#55FFFF")
    MVP = Rank("MVP", "MVP", color="#55FFFF")
    MVP_PLUS = Rank("MVP_PLUS", "MVP+", color="#55FFFF", plus_color="#AA0000")
    SUPERSTAR = Rank("SUPERSTAR", "MVP++", color="#FFAA00", plus_color="#AA0000")
    YOUTUBER = Rank("YOUTUBER", "YOUTUBE", color="#FFFFFF", bracket_color="#AA0000")
    PIG = Rank("PIG+++", "PIG+++", color="#FF5SFF", plus_color="#55FFFF")
    BUILD_TEAM = Rank("BUILD TEAM", "BUILD TEAM", color="#00AAAA")
    HELPER = Rank("HELPER", "HELPER", color="#5555FF")
    MODERATOR = Rank("MODERATOR", "MOD", color="#00AA00")
    ADMIN = Rank("ADMIN", "ADMIN", color="#AA0000")
    SLOTH = Rank("SLOTH", "SLOTH", color="#AA0000")
    OWNER = Rank("OWNER", "OWNER", color="#AA0000")

    @classmethod
    def convert(cls, argument: dict):
        if argument.get("rank", None):
            for rank in Ranks:
                if rank.value.db_key == argument.get("rank"):
                    return rank

        elif argument.get("monthlyPackageRank", None):
            for rank in Ranks:
                if rank.value.db_key == argument.get("monthlyPackageRank"):
                    return rank

        elif argument.get("newPackageRank", None):
            for rank in Ranks:
                if rank.value.db_key == argument.get("newPackageRank"):
                    return rank

        elif argument.get("packageRank", None):
            for rank in Ranks:
                if rank.value.db_key == argument.get("packageRank"):
                    return rank

        return Ranks.DEFAULT






