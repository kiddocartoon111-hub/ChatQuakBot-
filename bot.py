# ChatQuakBot
# A Discord bot for ChatQuak

import os
import discord
from discord.ext import commands

# Initialize the bot
bot = commands.Bot(command_prefix='!', intents=discord.Intents.default())

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.command(name='ping')
async def ping(ctx):
    """Responds with pong"""
    await ctx.send('Pong!')

# Run the bot
if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN environment variable not set")
    else:
        bot.run(token)
