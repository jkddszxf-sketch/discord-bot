import discord
from discord import app_commands
from discord.ext import commands
import random
import os

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ.get("DISCORD_TOKEN")

# Role ID that can use /in-house
ALLOWED_ROLE_ID = 1483516493634207804

# Ping role ID
PING_ROLE_ID = 1452780529937154058

# Positions
POSITIONS = ["CF", "RW", "LW", "CM", "GK"]

# Styles by rarity
STYLES = {
    "RARE": ["Isagi", "Chigiri"],
    "EPIC": ["Hiori", "Gagamaru", "Otoya", "Bachira"],
    "LEGENDARY": ["King", "Nagi", "Reo", "Aiku", "Karasu"],
    "MYTHIC": ["Shidou", "Yukimiya", "Sae", "Kunigami", "Rin"]
}

# Active in-house games: {message_id: game_data}
active_games = {}


class GameData:
    def __init__(self, creator_id):
        self.creator_id = creator_id
        self.home = {}  # {position: (user_id, style)}
        self.away = {}  # {position: (user_id, style)}
        self.players = {}  # {user_id: (team, position, style)}
        self.message = None
        self.channel_id = None

    def get_home_styles(self):
        return [style for _, (_, style) in self.home.items()]

    def get_away_styles(self):
        return [style for _, (_, style) in self.away.items()]

    def is_full(self):
        return len(self.home) == 5 and len(self.away) == 5

    def add_player(self, user_id, position, style):
        """Add player to a random team. Returns (team, success, error_msg)"""
        home_has = position in self.home
        away_has = position in self.away

        if home_has and away_has:
            return None, False, "المركز ممتلئ! ❌"

        # Check if user already registered
        if user_id in self.players:
            return None, False, "أنت مسجل بالفعل! ❌"

        # Determine available teams for this position
        available_teams = []
        if not home_has:
            available_teams.append("home")
        if not away_has:
            available_teams.append("away")

        # Pick random team
        team = random.choice(available_teams)

        # Check style conflict in the chosen team
        if team == "home":
            team_styles = self.get_home_styles()
        else:
            team_styles = self.get_away_styles()

        if style in team_styles:
            # Try the other team if available
            other_team = "away" if team == "home" else "home"
            if other_team in available_teams:
                if other_team == "home":
                    other_styles = self.get_home_styles()
                else:
                    other_styles = self.get_away_styles()
                if style not in other_styles:
                    team = other_team
                else:
                    return None, False, "في أحد ماخذ الستايل هذا بكلا الفريقين! ❌"
            else:
                return None, False, "في أحد ماخذ الستايل هذا بفريقك! ❌"

        # Add to team
        if team == "home":
            self.home[position] = (user_id, style)
        else:
            self.away[position] = (user_id, style)

        self.players[user_id] = (team, position, style)
        return team, True, None

    def remove_player(self, user_id):
        """Remove a player from the game"""
        if user_id not in self.players:
            return False
        team, position, style = self.players[user_id]
        if team == "home":
            del self.home[position]
        else:
            del self.away[position]
        del self.players[user_id]
        return True

    def build_embed(self):
        """Build the embed message"""
        def format_slot(team_dict, pos):
            if pos in team_dict:
                user_id, style = team_dict[pos]
                return f"<@{user_id}> - {style}"
            return ""

        home_cf = format_slot(self.home, "CF")
        home_rw = format_slot(self.home, "RW")
        home_lw = format_slot(self.home, "LW")
        home_cm = format_slot(self.home, "CM")
        home_gk = format_slot(self.home, "GK")

        away_cf = format_slot(self.away, "CF")
        away_rw = format_slot(self.away, "RW")
        away_lw = format_slot(self.away, "LW")
        away_cm = format_slot(self.away, "CM")
        away_gk = format_slot(self.away, "GK")

        description = (
            "————————————\n\n"
            "**🏠 Home**\n\n"
            f"**CF :** {home_cf}\n"
            f"**RW :** {home_rw}\n"
            f"**LW :** {home_lw}\n"
            f"**CM :** {home_cm}\n"
            f"**GK :** {home_gk}\n\n"
            "————————————\n\n"
            "**✈️ Away**\n\n"
            f"**CF :** {away_cf}\n"
            f"**RW :** {away_rw}\n"
            f"**LW :** {away_lw}\n"
            f"**CM :** {away_cm}\n"
            f"**GK :** {away_gk}\n\n"
            "————————————"
        )

        embed = discord.Embed(
            title="⚽ Inhouse",
            description=description,
            color=discord.Color.blue()
        )
        return embed


class PositionSelect(discord.ui.Select):
    def __init__(self, game_id):
        self.game_id = game_id
        options = [
            discord.SelectOption(label="CF", value="CF", description="Center Forward"),
            discord.SelectOption(label="RW", value="RW", description="Right Wing"),
            discord.SelectOption(label="LW", value="LW", description="Left Wing"),
            discord.SelectOption(label="CM", value="CM", description="Center Midfield"),
            discord.SelectOption(label="GK", value="GK", description="Goalkeeper"),
        ]
        super().__init__(placeholder="Your Position?", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        if interaction.user.id in game.players:
            await interaction.response.send_message("أنت مسجل بالفعل! ❌", ephemeral=True)
            return

        position = self.values[0]

        # Check if position is full
        home_has = position in game.home
        away_has = position in game.away
        if home_has and away_has:
            await interaction.response.send_message("المركز ممتلئ! ❌", ephemeral=True)
            return

        # Move to rarity selection
        view = RarityView(self.game_id, position)
        await interaction.response.send_message("**Style Rarity?**", view=view, ephemeral=True)


class RaritySelect(discord.ui.Select):
    def __init__(self, game_id, position):
        self.game_id = game_id
        self.position = position
        options = [
            discord.SelectOption(label="RARE", value="RARE", emoji="🟢"),
            discord.SelectOption(label="EPIC", value="EPIC", emoji="🟣"),
            discord.SelectOption(label="LEGENDARY", value="LEGENDARY", emoji="🟡"),
            discord.SelectOption(label="MYTHIC", value="MYTHIC", emoji="🔴"),
        ]
        super().__init__(placeholder="Style Rarity?", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        if interaction.user.id in game.players:
            await interaction.response.send_message("أنت مسجل بالفعل! ❌", ephemeral=True)
            return

        rarity = self.values[0]
        styles = STYLES[rarity]

        view = StyleView(self.game_id, self.position, rarity)
        await interaction.response.edit_message(content="**You're Style?**", view=view)


class StyleSelect(discord.ui.Select):
    def __init__(self, game_id, position, rarity):
        self.game_id = game_id
        self.position = position
        self.rarity = rarity
        styles = STYLES[rarity]
        options = [discord.SelectOption(label=s, value=s) for s in styles]
        super().__init__(placeholder="You're Style?", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        if interaction.user.id in game.players:
            await interaction.response.send_message("أنت مسجل بالفعل! ❌", ephemeral=True)
            return

        style = self.values[0]
        position = self.position

        # Try to add the player
        team, success, error_msg = game.add_player(interaction.user.id, position, style)

        if not success:
            await interaction.response.edit_message(content=error_msg, view=None)
            return

        team_name = "Home 🏠" if team == "home" else "Away ✈️"
        await interaction.response.edit_message(
            content=f"تم تسجيلك بنجاح! ✅\n**الفريق:** {team_name}\n**المركز:** {position}\n**الستايل:** {style}",
            view=None
        )

        # Update the main message
        try:
            channel = bot.get_channel(game.channel_id)
            if channel:
                msg = await channel.fetch_message(self.game_id)
                embed = game.build_embed()
                view = InhouseView(self.game_id)
                # Add start button if game is full
                if game.is_full():
                    view = InhouseViewFull(self.game_id, game.creator_id)
                await msg.edit(embed=embed, view=view, content=f"<@&{PING_ROLE_ID}>")
        except Exception as e:
            print(f"Error updating message: {e}")


class RarityView(discord.ui.View):
    def __init__(self, game_id, position):
        super().__init__(timeout=120)
        self.add_item(RaritySelect(game_id, position))


class StyleView(discord.ui.View):
    def __init__(self, game_id, position, rarity):
        super().__init__(timeout=120)
        self.add_item(StyleSelect(game_id, position, rarity))


class LeaveButton(discord.ui.Button):
    def __init__(self, game_id):
        self.game_id = game_id
        super().__init__(label="خروج", style=discord.ButtonStyle.danger, custom_id=f"leave_{game_id}")

    async def callback(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        if interaction.user.id not in game.players:
            await interaction.response.send_message("أنت مو مسجل! ❌", ephemeral=True)
            return

        game.remove_player(interaction.user.id)
        await interaction.response.send_message("تم إخراجك بنجاح! ✅", ephemeral=True)

        # Update the main message
        try:
            channel = bot.get_channel(game.channel_id)
            if channel:
                msg = await channel.fetch_message(self.game_id)
                embed = game.build_embed()
                view = InhouseView(self.game_id)
                await msg.edit(embed=embed, view=view, content=f"<@&{PING_ROLE_ID}>")
        except Exception as e:
            print(f"Error updating message: {e}")


class StartMatchButton(discord.ui.Button):
    def __init__(self, game_id, creator_id):
        self.game_id = game_id
        self.creator_id = creator_id
        super().__init__(label="بداية المباراة", style=discord.ButtonStyle.success, custom_id=f"start_{game_id}")

    async def callback(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("بس اللي سوا الأمر يقدر يبدأ المباراة! ❌", ephemeral=True)
            return

        # Show modal for server link
        modal = ServerLinkModal(self.game_id)
        await interaction.response.send_modal(modal)


class ServerLinkModal(discord.ui.Modal, title="رابط السيرفر"):
    server_link = discord.ui.TextInput(
        label="رابط السيرفر",
        placeholder="حط رابط السيرفر هنا...",
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, game_id):
        super().__init__()
        self.game_id = game_id

    async def on_submit(self, interaction: discord.Interaction):
        game = active_games.get(self.game_id)
        if not game:
            await interaction.response.send_message("هذا الانهاوس انتهى! ❌", ephemeral=True)
            return

        link = self.server_link.value

        # Send DM to all players
        success_count = 0
        fail_count = 0
        for user_id in game.players:
            try:
                user = await bot.fetch_user(user_id)
                embed = discord.Embed(
                    title="⚽ رابط الانهاوس",
                    description=f"هذا رابط الانهاوس:\n\n**{link}**",
                    color=discord.Color.green()
                )
                await user.send(embed=embed)
                success_count += 1
            except Exception as e:
                fail_count += 1
                print(f"Failed to DM user {user_id}: {e}")

        await interaction.response.send_message(
            f"تم إرسال رابط السيرفر لجميع اللاعبين! ✅\n✉️ تم الإرسال: {success_count}\n❌ فشل: {fail_count}",
            ephemeral=True
        )

        # Also send in the channel
        try:
            channel = bot.get_channel(game.channel_id)
            if channel:
                mentions = " ".join([f"<@{uid}>" for uid in game.players])
                embed = discord.Embed(
                    title="⚽ بداية المباراة!",
                    description=f"رابط السيرفر:\n**{link}**\n\n{mentions}",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)
        except Exception as e:
            print(f"Error sending to channel: {e}")


class InhouseView(discord.ui.View):
    def __init__(self, game_id):
        super().__init__(timeout=None)
        self.add_item(PositionSelect(game_id))
        self.add_item(LeaveButton(game_id))


class InhouseViewFull(discord.ui.View):
    def __init__(self, game_id, creator_id):
        super().__init__(timeout=None)
        self.add_item(PositionSelect(game_id))
        self.add_item(LeaveButton(game_id))
        self.add_item(StartMatchButton(game_id, creator_id))


@bot.event
async def on_ready():
    print(f"Bot is ready! Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")


@bot.tree.command(name="in-house", description="ابدأ انهاوس جديد")
async def inhouse(interaction: discord.Interaction):
    # Check if user has the allowed role
    has_role = False
    if interaction.guild:
        member = interaction.guild.get_member(interaction.user.id)
        if member:
            for role in member.roles:
                if role.id == ALLOWED_ROLE_ID:
                    has_role = True
                    break

    if not has_role:
        await interaction.response.send_message("ما عندك صلاحية تستخدم هذا الأمر! ❌", ephemeral=True)
        return

    # Create game data
    game = GameData(interaction.user.id)
    game.channel_id = interaction.channel_id

    # Build embed
    embed = game.build_embed()

    # Send the message first to get the message ID
    await interaction.response.send_message(
        content=f"<@&{PING_ROLE_ID}>",
        embed=embed
    )

    # Get the message
    msg = await interaction.original_response()
    game.message = msg

    # Store game with message ID as key
    active_games[msg.id] = game

    # Now add the view
    view = InhouseView(msg.id)
    await msg.edit(view=view)


bot.run(TOKEN)
