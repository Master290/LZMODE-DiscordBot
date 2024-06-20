import discord
from discord.ext import commands, tasks
import youtube_dl
import asyncio
import ffmpeg
import aiohttp
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot(command_prefix='!', intents=intents)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    bot.loop.create_task(update_bot_status())

async def update_bot_status():
    while True:
        now_playing_data = await fetch_now_playing()
        if now_playing_data and now_playing_data[0]:
            current_song = now_playing_data[0]['now_playing']['song']
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{current_song['artist']} - {current_song['title']}"))
        await asyncio.sleep(10)

async def fetch_now_playing():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://cast.lzmode.online/api/nowplaying') as response:
            return await response.json()

def fetch_track_art(artist, track):
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

    spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))
    query = f"artist:{artist} track:{track}"
    result = spotify.search(q=query, type='track', limit=1)
    
    if result['tracks']['items']:
        return result['tracks']['items'][0]['album']['images'][0]['url']
    
    return 'https://cast.lzmode.online/static/uploads/album_art.1712338724.png'

async def update_now_playing_message(channel, message):
    while True:
        now_playing_data = await fetch_now_playing()
        if now_playing_data and now_playing_data[0]:
            current_song = now_playing_data[0]['now_playing']['song']
            dj_name = now_playing_data[0]['now_playing']['streamer']
            first_artist = current_song['artist'].split(',')[0].strip()
            track_art = fetch_track_art(first_artist, current_song['title'])
            embed = discord.Embed(
                title=current_song['title'],
                description=f"Artist: {current_song['artist']}",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=track_art)
            embed.set_footer(text=f"DJ: {dj_name}")
            await message.edit(embed=embed)
        await asyncio.sleep(10)

@bot.tree.command(name='play', description='Play a live radio stream')
async def play(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("You're not in a voice channel.", ephemeral=True)
        return

    channel = interaction.user.voice.channel

    if interaction.guild.voice_client is None:
        await channel.connect()

    hardcoded_url = 'https://cast.lzmode.online/listen/lzmode/mobileapp.mp3'

    async with interaction.channel.typing():
        player = await YTDLSource.from_url(hardcoded_url, loop=bot.loop, stream=True)
        interaction.guild.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)

    now_playing_data = await fetch_now_playing()
    if now_playing_data and now_playing_data[0]:
        current_song = now_playing_data[0]['now_playing']['song']
        dj_name = now_playing_data[0]['now_playing']['streamer']
        first_artist = current_song['artist'].split(',')[0].strip()
        track_art = fetch_track_art(first_artist, current_song['title'])
        embed = discord.Embed(
            title=current_song['title'],
            description=f"Artist: {current_song['artist']}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=track_art)
        embed.set_footer(text=f"DJ: {dj_name}")
        await interaction.response.send_message(embed=embed)
        followup_message = await interaction.followup.send(embed=embed)
        bot.loop.create_task(update_now_playing_message(interaction.channel, followup_message))

@bot.tree.command(name='stop', description='Stop the radio and disconnect the bot')
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Disconnected.")
    else:
        await interaction.response.send_message("You're not in a voice channel.", ephemeral=True)

bot.run(os.getenv('DISCORD_TOKEN'))
