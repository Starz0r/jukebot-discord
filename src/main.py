import os
import queue
import asyncio
import threading
from dataclasses import dataclass

import discord
import youtube_dl

from discord.ext import commands

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description="Relatively simple music bot example",
)

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
    "source_address": "0.0.0.0",  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {"options": "-vn"}

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
    songs: queue.Queue[Song] = queue.Queue()
    playable = threading.Lock()
    def __init__(self, bot):
        print("Called")
        self.bot = bot

        threading.Thread(target=self.play_from_queue).start()

    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def play(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        # if we aren't in a voice channel, join the channel the user was in
        if ctx.voice_client is None and ctx.author.voice is not None:
            await ctx.author.voice.channel.connect()

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

    def play_from_queue(self):
        """
        Attempts to dequeue a song over yt-dl, and stream it through
        a VC connection. Clears the queue if there are no listeners.
        """
        while True:

            # block for queue
            self.playable.acquire()

            song = self.songs.get()
            # check for any listeners
            if len(self.bot.voice_clients) == 0:
                # clear queue if noone's listening
                # HACK: huge data race here when clearing and a song is added
                while not self.songs.empty():
                    self.songs.get_nowait()
                # TODO: leaving the vc

                self.playable.release()
                continue

            player = asyncio.run(YTDLSource.from_url(song.url, loop=None, stream=True))

            vc: discord.VoiceClient = self.bot.voice_clients[0]
            vc.play(player, after=lambda e: self.song_finished(e))

            # notify users
            embed = discord.Embed(
                title=f"**{song.title}**", url=song.url, description=f"By {song.name}"
            )
            embed.set_author(name="🎶 Now Playing!")
            embed.set_thumbnail(url=song.preview)
            loop = asyncio.new_event_loop()
            loop.run_until_complete(asyncio.create_task(self.chat.send(embed=embed)))

    def song_finished(self, e: Exception):
        self.playable.release()
        if e:
            print(f"Player error: {e}")
        print(f"Song finished, moving on! err?: {e}")

    @classmethod
    async def get_url_info(
        cls, url: str, loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    ) -> dict[str, Any]:
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )
        if not data:
            raise Exception("Song info could not be extracted")
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


def main():
    bot.add_cog(Radio(bot))
    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
