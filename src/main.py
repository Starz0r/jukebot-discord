import asyncio
import os
import queue
import threading
from dataclasses import dataclass
from typing import Optional, Any
import platform
import time

import discord  # TODO: migrate to disnake
import yt_dlp as youtube_dl  # TODO: migrate to yt-dlp
from discord.ext import commands
from git import Repo

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description="Relatively simple music bot example",
)

# TODO: logging

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ""

ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    # bind to ipv4 since ipv6 addresses cause issues sometimes
    "source_address": "0.0.0.0",
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36"
    },
    "prefer_ffmpeg": True,
    "dynamic_mpd": True,
    "extractor_retries": 10,
    "noprogress": True,
}

ffmpeg_options = {
    "options": "-vn",
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 7",
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )

        if "entries" in data:
            # take first item from a playlist
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


@dataclass
class Song:
    title: str
    url: str
    name: str  # uploader
    preview: str  # thumbnail url


class Radio(commands.Cog):
    bot: commands.Bot
    songs: queue.Queue[Song] = queue.Queue()
    playable = threading.Lock()
    chat: Optional[discord.abc.Messageable]

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def play(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        # TODO: verify the request is a valid URL
        # TODO: do a naive request to see if the URL is reachable
        # TODO: if it's not a url, search on youtube, grab the first result

        info = await self.get_url_info(url)
        song = Song(
            info["title"],
            info["webpage_url"],
            name=info["uploader"],
            preview=info["thumbnail"],
        )
        self.songs.put(song)
        self.chat = ctx

        if not self.bot.voice_clients[0].is_playing():
            await self.dequeue_next_song()
        elif self.bot.voice_clients[0].is_playing():
            embed = discord.Embed(
                title=f"**{song.title}**", url=song.url, description=f"By {song.name}"
            )
            embed.set_author(name="📑 Queued Song")
            embed.set_thumbnail(url=song.preview)
            await ctx.send(embed=embed)

    async def dequeue_next_song(self):
        song: Song
        try:
            song = self.songs.get(block=False)
        except queue.Empty:
            return

        if len(self.bot.voice_clients) == 0:
            while not self.songs.empty():
                self.songs.get_nowait()
            return

        # TODO: use the currently running event loop
        player = await YTDLSource.from_url(song.url, loop=None, stream=True)

        vc: discord.VoiceClient = self.bot.voice_clients[0]
        vc.play(player, after=lambda e: self.song_finished(e))

        # notify users
        embed = discord.Embed(
            title=f"**{song.title}**", url=song.url, description=f"By {song.name}"
        )
        embed.set_author(name="🎶 Now Playing!")
        embed.set_thumbnail(url=song.preview)
        await self.chat.send(embed=embed)

    def song_finished(self, e: Exception):
        fut = self.dequeue_next_song()
        if e:
            print(f"Player error: {e}")
        print(f"Song finished, moving on! err?: {e}")
        asyncio.run_coroutine_threadsafe(fut, self.bot.loop).result()

    @classmethod
    async def get_url_info(
        cls, url: str, loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    ) -> dict[str, Any]:
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )
        if not data:
            raise Exception("Song info could not be extracted")

        if "entries" in data:
            # take first item from a playlist
            data = data["entries"][0]

        return data

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Changed volume to {volume}%")

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""

        await ctx.voice_client.disconnect()

    @play.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        # elif ctx.voice_client.is_playing():
        #   ctx.voice_client.stop()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    repo = Repo(os.getcwd())
    chan = bot.get_channel(int(os.getenv("DISCORD_NOTIFYCHAN")))
    await chan.send(
        "Jukebot is now online! Last changes at: "
        + time.strftime(
            "%B %d, %Y (%H:%M:%S)", time.gmtime(repo.heads.master.commit.committed_date)
        )
        + ", Git Commit: "
        + repo.heads.master.commit.__str__()
    )


def main():
    # HACK: auto detect library location
    if platform.system() != "Windows":
        discord.opus.load_opus("libopus.so.0")
    bot.add_cog(Radio(bot))
    # TODO: handle sigint and sigterm
    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
