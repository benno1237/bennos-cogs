from redbot.core import commands
import enum

class gamemode:
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


class gamemodes(enum.Enum):
    ARCADE = gamemode(
        14, "ARCADE", "Arcade"
    )
    ARENA = gamemode(
        17, "ARENA", "Arena"
    )
    BATTLEGROUND = gamemode(
        23, "BATTLEGROUND", "Battleground", "Warlords"
    )
    BEDWARS = gamemode(
        58, "BEDWARS", "Bedwars", "Bed Wars", "Experience"
    )
    BUILD_BATTLE = gamemode(
        60, "BUILD_BATTLE", "BuildBattle", "Build Battle"
    )
    DUELS = gamemode(
        61, "DUELS", "Duels"
    )
    GINGERBREAD = gamemode(
        25, "GINGERBREAD", "GingerBread", "Turbo Kart Racers"
    )
    SURVIVAL_GAMES = gamemode(
        5, "SURVIVAL_GAMES", "HungerGames", "Blitz Survival Games"
    )
    MCGO = gamemode(
        21, "MCGO", "MCGO", "Cops and Crims"
    )
    MURDER_MYSTERY = gamemode(
        59, "MURDER_MYSTERY", "MurderMystery", "Murder Mystery"
    )
    PAINTBALL = gamemode(
        4, "PAINTBALL", "Paintball"
    )
    QUAKECRAFT = gamemode(
        2, "QUAKECRAFT", "Quake"
    )
    SKYWARS = gamemode(
        51, "SKYWARS", "SkyWars", "SkyWars", "skywars_experience"
    )
    SKYCLASH = gamemode(
        55, "SKYCLASH", "SkyClash"
    )
    SPEED_UHC = gamemode(
        54, "SPEED_UHC", "SpeedUHC", "Speed UHC"
    )
    SUPER_SMASH = gamemode(
        24, "SUPER_SMASH", "SuperSmash", "Smash Heroes"
    )
    TNTGAMES = gamemode(
        6, "TNTGAMES", "TNTGames", "TNT Games"
    )
    TRUECOMBAT = gamemode(
        52, "TRUECOMBAT", "TrueCombat", "Crazy Walls"
    )
    UHC = gamemode(
        20, "UHC", "UHC", "UHC Champions"
    )
    VAMPIREZ = gamemode(
        7, "VAMPIREZ", "VampireZ"
    )
    WALLS = gamemode(
        3, "WALLS", "Walls"
    )
    WALLS3 = gamemode(
        13, "WALLS3", "Walls3", "Mega Walls"
    )

    @classmethod
    async def convert(cls, ctx, argument):
        for gm in gamemodes:
            gm = gm.value
            if argument == gm.id:
                return gm
            elif argument.lower() == gm.type_name.lower():
                return gm
            elif argument.lower() == gm.db_key.lower():
                return gm
            elif argument.lower() == gm.clean_name.lower():
                return gm


class scope(enum.Enum):
    GLOBAL = "global"
    GUILD = "guild"
    USER = "user"


class colortypes(enum.Enum):
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
    ):
        self.db_key = db_key
        self.clear_name = clear_name
        self.color = color


class Ranks(enum.Enum):
    DEFAULT = Rank("NORMAL", "")
    VIP = Rank("VIP", "VIP")
    VIP_PLUS = Rank("VIP_PLUS", "VIP+")
    MVP = Rank("MVP", "MVP")
    MVP_PLUS = Rank("MVP_PLUS", "MVP+")
    SUPERSTAR = Rank("SUPERSTAR", "MVP++")
    YOUTUBER = Rank("YOUTUBER", "YOUTUBE")
    PIG = Rank("PIG+++", "PIG+++")
    BUILD_TEAM = Rank("BUILD TEAM", "BUILD TEAM")
    HELPER = Rank("HELPER", "HELPER")
    MODERATOR = Rank("MODERATOR", "MOD")
    ADMIN = Rank("ADMIN", "ADMIN")
    SLOTH = Rank("SLOTH", "SLOTH")
    OWNER = Rank("OWNER", "OWNER")

    @classmethod
    async def convert(cls, ctx, argument):
        for rank in Ranks:
            if rank.value.db_key == argument:
                return rank





