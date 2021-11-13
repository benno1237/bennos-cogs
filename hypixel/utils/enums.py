import enum

class gamemode:
    def __init__(
            self,
            id: int,
            type_name: str,
            db_name: str,
            clean_name: str = None,
            xp_key: str = None
    ):
        self._id = id
        self._type_name = type_name
        self._db_name = db_name
        self._clean_name = clean_name if clean_name else db_name
        self._xp_key = xp_key

    @property
    def id(self):
        return self._id

    @property
    def type_name(self):
        return self._type_name

    @property
    def db_name(self):
        return self._db_name

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
    BUILDBATTLE = gamemode(
        60, "BUILD_BATTLE", "BuildBattle", "Build Battle"
    )
    DUELS = gamemode(
        61, "DUELS", "Duels"
    )
    GINGERBREAD = gamemode(
        25, "GINGERBREAD", "GingerBread", "Turbo Kart Racers"
    )
    HUNGERGAMES = gamemode(
        5, "SURVIVAL_GAMES", "HungerGames", "Blitz Survival Games"
    )
    MCGO = gamemode(
        21, "MCGO", "MCGO", "Cops and Crims"
    )
    MURDERMYSTERY = gamemode(
        59, "MURDER_MYSTERY", "MurderMystery", "Murder Mystery"
    )
    PAINTBALL = gamemode(
        4, "PAINTBALL", "Paintball"
    )
    QUAKECRAFT = gamemode(
        2, "QUAKECRAFT", "Quake"
    )
    SKYWARS = gamemode(
        5, "SURVIVAL_GAMES", "HungerGames", "Blitz Survival Games", "skywars_experience"
    )
    SKYCLASH = gamemode(
        55, "SKYCLASH", "SkyClash"
    )
    SPEEDUHC = gamemode(
        54, "SPEED_UHC", "SpeedUHC", "Speed UHC"
    )
    SUPERSMASH = gamemode(
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

class scope(enum.Enum):
    GLOBAL = "global"
    GUILD = "guild"
    USER = "user"

class colortypes(enum.Enum):
    HSB = "hsb"
    HSL = "hsl"
    HSV = "hsv"
    RGB = "rgb"



