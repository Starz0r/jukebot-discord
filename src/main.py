import os
import queue
import asyncio
import threading

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


class Radio(commands.Cog):
    def __init__(self, bot):
        print("Called")
        self.bot = bot
        self.songs = queue.Queue()
        self.queue_lock = threading.Lock()
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

        if len(self.bot.voice_clients) == 0:
            # TODO: clear the queue
            pass

        # TODO: verify the request is a valid URL
        # TODO: do a naive request to see if the URL is reachable
        # TODO: if it's not a url, search on youtube, grab the first result
        self.songs.put(url)

    def play_from_queue(self):
        while True:
            print("Locking Queue.")
            self.queue_lock.acquire(blocking=True)
            print("Checking for Voice Clients")
            if len(self.bot.voice_clients) == 0:
                print("No VC, releasing the queue lock")
                self.queue_lock.release()
                continue
            print("Waiting for song.")
            url = self.songs.get()
            print("New song!")

            vc = self.bot.voice_clients[0]
            player = asyncio.run(YTDLSource.from_url(url, loop=None, stream=True))

            vc.play(player, after=lambda e: self.song_finished(e))

            # await ctx.send(f"Now playing: {player.title}")

    def song_finished(self, e: Exception):
        if e:
            print(f"Player error: {e}")
        print(f"Song finished, moving on! err?: {e}")
        self.queue_lock.release()

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
