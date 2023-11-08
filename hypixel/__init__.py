from .hypixel import Hypixel

async def setup(bot):
    await bot.add_cog(Hypixel(bot))

