from .hypixel import Hypixel

def setup(bot):
    bot.add_cog(Hypixel(bot))

