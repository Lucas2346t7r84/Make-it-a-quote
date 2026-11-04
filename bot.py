import io
import os
import re
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps, ImageDraw, ImageFont

intents = discord.Intents.default()
intents.message_content = True

class QuoteBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Commands synced successfully!")

bot = QuoteBot()

def generate_quote_card(text: str, author_name: str, avatar_bytes: bytes = None, media_bytes: bytes = None) -> io.BytesIO:
    width = 800
    background_color = (15, 15, 15)
    text_color = (240, 240, 240)
    author_color = (160, 160, 160)

    # 1. Load fonts
    try:
        font_quote = ImageFont.truetype("arial.ttf", 26)
        font_author = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font_quote = ImageFont.load_default()
        font_author = ImageFont.load_default()

    # 2. Wrap text and calculate lines (if text is empty, skip text block)
    lines = []
    if text:
        max_line_length = 33
        words = text.split(' ')
        current_line = ""
        
        for word in words:
            if len(current_line + " " + word) <= max_line_length:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
            
    formatted_text = f'"{chr(10).join(lines)}"' if lines else ""
    
    # 3. Calculate dynamic height based on text and media
    text_block_height = (len(lines) * 36 + 40) if lines else 20
    media_height = 220 if media_bytes else 0
    calculated_height = max(400, text_block_height + media_height + 60)

    # Create base image
    img = Image.new("RGB", (width, calculated_height), color=background_color)
    draw = ImageDraw.Draw(img)

    # 4. Paste and INVERT user avatar on the left (spanning full height)
    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
            avatar_img = avatar_img.resize((calculated_height, calculated_height))
            avatar_img = ImageOps.invert(avatar_img) # Inverted colors only for avatar
            img.paste(avatar_img, (0, 0))
            
            # Dark overlay mask
            overlay = Image.new("RGBA", (calculated_height, calculated_height), (15, 15, 15, 140))
            img.paste(overlay, (0, 0), overlay)
        except Exception as e:
            print(f"Error loading/inverting avatar: {e}")

    # 5. Draw Text on the right side
    start_x = 420
    start_y = 50
    current_y = start_y

    if formatted_text:
        draw.text((start_x, current_y), formatted_text, fill=text_color, font=font_quote)
        current_y += len(lines) * 36 + 15

    # 6. Handle Media (Images, Stickers, GIFs) — NOT inverted
    if media_bytes:
        try:
            media_img = Image.open(io.BytesIO(media_bytes))
            if hasattr(media_img, "is_animated") and media_img.is_animated:
                media_img.seek(0) # Grab first frame for GIFs/animated stickers
            media_img = media_img.convert("RGB")
            media_img.thumbnail((340, 200)) # Fit nicely on the card
            img.paste(media_img, (start_x, current_y))
            current_y += media_img.height + 15
        except Exception as e:
            print(f"Error loading media attachment/sticker: {e}")

    # Draw Author Name
    author_text = f"— {author_name}"
    draw.text((start_x, current_y + 10), author_text, fill=author_color, font=font_author)

    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")

# Context Menu Command (Right-click -> Apps -> Make it a Quote)
@bot.tree.context_menu(name="Make it a Quote")
async def quote_context(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer()

    avatar_bytes = None
    if message.author.display_avatar:
        avatar_bytes = await message.author.display_avatar.with_format("png").read()

    # Clean text: remove raw URLs (like image links or Tenor GIF links) so they don't get printed
    clean_text = re.sub(r'https?://\S+', '', message.content).strip()

    media_bytes = None
    async with aiohttp.ClientSession() as session:
        # Priority 1: Check standard file attachments (Images / GIFs)
        if message.attachments:
            attachment = message.attachments[0]
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.apng']):
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        media_bytes = await resp.read()

        # Priority 2: Check stickers if no attachment was found
        if not media_bytes and message.stickers:
            sticker = message.stickers[0]
            async with session.get(sticker.url) as resp:
                if resp.status == 200:
                    media_bytes = await resp.read()

        # Priority 3: Check embeds (like Tenor GIFs or external image embeds)
        if not media_bytes and message.embeds:
            for embed in message.embeds:
                target_url = embed.image.url or embed.thumbnail.url or (embed.video.url if embed.video else None)
                if target_url:
                    async with session.get(target_url) as resp:
                        if resp.status == 200:
                            media_bytes = await resp.read()
                            break

    buffer = generate_quote_card(
        text=clean_text,
        author_name=message.author.display_name,
        avatar_bytes=avatar_bytes,
        media_bytes=media_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    await interaction.followup.send(file=file)

# Slash Command (/quote)
@bot.tree.command(name="quote", description="Quote a specific text manually")
@app_commands.describe(text="The message to quote", author="Who said it (optional)")
async def quote_slash(interaction: discord.Interaction, text: str, author: discord.User = None):
    await interaction.response.defer()

    target_user = author or interaction.user
    avatar_bytes = None
    if target_user.display_avatar:
        avatar_bytes = await target_user.display_avatar.with_format("png").read()

    buffer = generate_quote_card(
        text=text,
        author_name=target_user.display_name,
        avatar_bytes=avatar_bytes
    )

    file = discord.File(fp=buffer, filename="quote.png")
    await interaction.followup.send(file=file)

if __name__ == "__main__":
    TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
    bot.run(TOKEN)
