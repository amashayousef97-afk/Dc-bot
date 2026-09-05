import asyncio
import json
import os
import random
import re
import discord
from discord import app_commands, ui
from discord.ext import commands

ALLOWED_ROLE_ID = 1528562387920093375
DB_FILE = "sources.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# --- Persistence Functions ---
def load_sources():
  if os.path.exists(DB_FILE):
    try:
      with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception as e:
      print(f"Error loading sources: {e}")
      return []
  return []


def save_sources_to_file():
  try:
    with open(DB_FILE, "w", encoding="utf-8") as f:
      json.dump(saved_sources, f, ensure_ascii=False, indent=2)
  except Exception as e:
    print(f"Error saving sources: {e}")


saved_sources = load_sources()
is_leaking = False


def is_staff(interaction: discord.Interaction) -> bool:
  if not interaction.guild:
    return False
  return any(role.id == ALLOWED_ROLE_ID for role in interaction.user.roles)


def extract_source_name(filename: str, content: str) -> str:
  if filename:
    clean_name = filename.rsplit(".", 1)[0]
    return clean_name.lower().strip()

  lines = [l.strip() for l in content.split("\n") if l.strip()]
  if lines:
    first_line = lines[0]
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", first_line)
    if cleaned:
      return cleaned.lower()

  return "unnamed_source"


# --- Poll System with Duration and User Details ---
class PollView(ui.View):

  def __init__(self, options: list, duration_seconds: int, question: str):
    super().__init__(timeout=duration_seconds)
    self.options = options
    self.question = question
    self.user_choices = {}
    self.votes = {opt: 0 for opt in options}

    for option in options:
      btn = ui.Button(
          label=f"{option} (0)",
          style=discord.ButtonStyle.primary,
          custom_id=f"poll_{option}",
      )
      btn.callback = self.make_callback(option)
      self.add_item(btn)

  def make_callback(self, option_name: str):
    async def callback(interaction: discord.Interaction):
      if interaction.user.id in self.user_choices:
        await interaction.response.send_message(
            "❌ You have already voted in this poll!", ephemeral=True
        )
        return

      self.user_choices[interaction.user.id] = (
          interaction.user.display_name,
          option_name,
      )
      self.votes[option_name] += 1

      for item in self.children:
        if isinstance(item, ui.Button):
          opt_text = item.custom_id.replace("poll_", "")
          item.label = f"{opt_text} ({self.votes[opt_text]})"

      await interaction.response.edit_message(view=self)
      await interaction.followup.send(
          f"✅ Your vote for **{option_name}** has been recorded!", ephemeral=True
      )

    return callback

  async def on_timeout(self):
    for item in self.children:
      item.disabled = True

    details = (
        "\n".join(
            [f"• **{name}**: {choice}" for name, choice in self.user_choices.values()]
        )
        if self.user_choices
        else "No votes submitted."
    )

    embed = discord.Embed(
        title=f"📊 Poll Ended: {self.question}",
        description=f"**Results:**\n{details}",
        color=discord.Color.red(),
    )
    if hasattr(self, "message") and self.message:
      await self.message.edit(embed=embed, view=self)


# --- Giveaway View ---
class GiveawayView(ui.View):

  def __init__(self, duration_seconds: int):
    super().__init__(timeout=duration_seconds)
    self.participants = set()

  @ui.button(
      label="Enter Giveaway 🎉",
      style=discord.ButtonStyle.success,
      custom_id="join_giveaway",
  )
  async def join_giveaway(
      self, interaction: discord.Interaction, button: ui.Button
  ):
    if interaction.user.id in self.participants:
      await interaction.response.send_message(
          "❌ You are already entered in this giveaway!", ephemeral=True
      )
    else:
      self.participants.add(interaction.user.id)
      await interaction.response.send_message(
          "✅ You've entered the giveaway!", ephemeral=True
      )


# --- Search Sources Pagination View ---
class SourcePaginationView(ui.View):

  def __init__(self, matched_sources: list, query: str, user_id: int):
    super().__init__(timeout=180)
    self.sources = matched_sources
    self.query = query
    self.user_id = user_id
    self.current_page = 0
    self.total_pages = len(matched_sources)

    self.update_buttons()

  def update_buttons(self):
    self.prev_btn.disabled = False
    self.next_btn.disabled = False
    self.page_indicator.label = f"{self.current_page + 1}"

  async def send_current_page(self, interaction: discord.Interaction):
    src = self.sources[self.current_page]
    filename = src.get("filename", f"{src['name']}.txt")
    content = src["content"]

    border = "--------------------------------------------------"
    header_text = (
        f"{border}\n📄 **{filename}**\n🔍 `{self.query}` · **{self.current_page + 1}**\n{border}"
    )

    file_path = f"temp_{filename}"
    with open(file_path, "w", encoding="utf-8") as f:
      f.write(content)

    file = discord.File(file_path, filename=filename)

    await interaction.response.edit_message(
        content=header_text, attachments=[file], view=self
    )

    if os.path.exists(file_path):
      os.remove(file_path)

  @ui.button(
      emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="prev_page"
  )
  async def prev_btn(self, interaction: discord.Interaction, button: ui.Button):
    if interaction.user.id != self.user_id:
      return await interaction.response.send_message(
          "❌ This search menu is not for you.", ephemeral=True
      )

    if self.current_page == 0:
      self.current_page = self.total_pages - 1
    else:
      self.current_page -= 1

    self.update_buttons()
    await self.send_current_page(interaction)

  @ui.button(
      label="1",
      style=discord.ButtonStyle.primary,
      disabled=True,
      custom_id="page_indicator",
  )
  async def page_indicator(
      self, interaction: discord.Interaction, button: ui.Button
  ):
    pass

  @ui.button(
      emoji="➡️", style=discord.ButtonStyle.secondary, custom_id="next_page"
  )
  async def next_btn(self, interaction: discord.Interaction, button: ui.Button):
    if interaction.user.id != self.user_id:
      return await interaction.response.send_message(
          "❌ This search menu is not for you.", ephemeral=True
      )

    if self.current_page == self.total_pages - 1:
      self.current_page = 0
    else:
      self.current_page += 1

    self.update_buttons()
    await self.send_current_page(interaction)


@bot.event
async def on_ready():
  print(f"Logged in successfully as {bot.user.name}")
  status_text = "FR HUB BOT BEST BOT FOR LEAKING TO BUY THE BOT FROM HERE https://discord.gg/dGUTthnv4X OPEN TICKET"
  activity = discord.Game(name=status_text)
  await bot.change_presence(status=discord.Status.online, activity=activity)
  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s)!")
  except Exception as e:
    print(f"Failed to sync: {e}")


# --- Prefix Search Command (!search) ---
@bot.command(name="search")
async def prefix_search(ctx, *, query: str = ""):
  if not query:
    return await ctx.send(
        "⚠️ Please specify a script name or query. Usage: `!search"
        " script_name`"
    )

  if not saved_sources:
    return await ctx.send("❌ No sources stored yet!")

  q = query.lower().strip()
  matched = [
      s
      for s in saved_sources
      if q in s["name"].lower() or q in s.get("filename", "").lower()
  ]

  if not matched:
    return await ctx.send(f'❌ nothing for "{query}" L')

  view = SourcePaginationView(matched, query, ctx.author.id)

  first_src = matched[0]
  filename = first_src.get("filename", f"{first_src['name']}.txt")
  border = "--------------------------------------------------"
  header_text = f"{border}\n📄 **{filename}**\n🔍 `{query}` · **1**\n{border}"

  file_path = f"temp_{filename}"
  with open(file_path, "w", encoding="utf-8") as f:
    f.write(first_src["content"])

  file = discord.File(file_path, filename=filename)
  await ctx.send(content=header_text, file=file, view=view)

  if os.path.exists(file_path):
    os.remove(file_path)


# --- Admin Slash Commands ---


@bot.tree.command(
    name="reload", description="Reload saved sources from local storage"
)
async def reload_cmd(interaction: discord.Interaction):
  if not is_staff(interaction):
    return await interaction.response.send_message(
        "You are not admin or staff", ephemeral=True
    )

  global saved_sources
  saved_sources = load_sources()
  await interaction.response.send_message(
      f"🔄 Reloaded sources! Total stored: **{len(saved_sources)}**",
      ephemeral=True,
  )


@bot.tree.command(
    name="say", description="Make the bot send a custom message up to 5 times"
)
@app_commands.describe(
    message="The message to send", amount="Number of times (1 to 5)"
)
@app_commands.choices(
    amount=[
        app_commands.Choice(name="1 time", value=1),
        app_commands.Choice(name="2 times", value=2),
        app_commands.Choice(name="3 times", value=3),
        app_commands.Choice(name="4 times", value=4),
        app_commands.Choice(name="5 times", value=5),
    ]
)
async def say(interaction: discord.Interaction, message: str, amount: int = 1):
  if not is_staff(interaction):
    return await interaction.response.send_message(
        "You are not admin or staff", ephemeral=True
    )

  await interaction.response.defer(ephemeral=True)

  for _ in range(amount):
    await interaction.channel.send(message)
    await asyncio.sleep(1)

  await interaction.followup.send(
      f"✅ Sent message **{amount}** time(s)!", ephemeral=True
  )


@bot.tree.command(
    name="take",
    description="Scrape and save ALL unique .txt/.lua sources in channel",
)
async def take(interaction: discord.Interaction):
  if not is_staff(interaction):
    return await interaction.response.send_message(
        "You are not admin or staff", ephemeral=True
    )

  await interaction.response.defer(ephemeral=True)

  count = 0
  channel = interaction.channel
  existing_contents = {s["content"].strip() for s in saved_sources}

  async for msg in channel.history(limit=None):
    if msg.attachments:
      for attachment in msg.attachments:
        if attachment.filename.endswith((".txt", ".lua")):
          try:
            content_bytes = await attachment.read()
            content_str = (
                content_bytes.decode("utf-8", errors="ignore").strip()
            )

            if content_str and content_str not in existing_contents:
              s_name = extract_source_name(attachment.filename, content_str)
              saved_sources.append({
                  "name": s_name,
                  "content": content_str,
                  "filename": attachment.filename,
              })
              existing_contents.add(content_str)
              count += 1
          except Exception as e:
            print(f"Failed to read attachment: {e}")

    if "```" in msg.content:
      matches = re.findall(r"```(?:\w+)?\n?(.*?)```", msg.content, re.DOTALL)
      for code in matches:
        code_clean = code.strip()
        if code_clean and code_clean not in existing_contents:
          s_name = extract_source_name("", code_clean)
          saved_sources.append({
              "name": s_name,
              "content": code_clean,
              "filename": f"{s_name}.txt",
          })
          existing_contents.add(code_clean)
          count += 1

  if count > 0:
    save_sources_to_file()

  await interaction.followup.send(
      f"✅ Scraped and saved **{count}** new source(s)!\nTotal stored unique"
      f" sources: **{len(saved_sources)}**",
      ephemeral=True,
  )


@bot.tree.command(
    name="leak", description="Send a specified amount of saved sources randomly"
)
@app_commands.describe(amount="How many sources to send?")
async def leak(interaction: discord.Interaction, amount: int):
  global is_leaking
  if not is_staff(interaction):
    return await interaction.response.send_message(
        "You are not admin or staff", ephemeral=True
    )

  if not saved_sources:
    return await interaction.response.send_message(
        "❌ No sources stored yet! Run `/take` first.", ephemeral=True
    )

  if amount <= 0:
    return await interaction.response.send_message(
        "❌ Please specify a number greater than 0.", ephemeral=True
    )

  await interaction.response.defer(ephemeral=True)

  actual_amount = min(amount, len(saved_sources))
  to_send = random.sample(saved_sources, actual_amount)

  header = "**leaked by fr hub bot best bot for leak**"
  await interaction.channel.send(header)

  is_leaking = True
  sent_count = 0
  nl, ticks = "\n", "```"

  for src in to_send:
    if not is_leaking:
      await interaction.channel.send("🛑 **Leak process stopped by user.**")
      break

    content = src["content"]
    name = src["name"]

    if len(content) > 1900:
      file_p = f"temp_{name}.txt"
      with open(file_p, "w", encoding="utf-8") as f:
        f.write
