import os
import random
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLE_ID = 1566790917107490877
ALLOWED_CHANNEL_IDS = {1571149166623592498, 1571136783029379202}

POSITIONS = ["CF", "RW", "LW", "CM", "GK"]
RARITIES = {
    "Rare 🔵": ["Isagi", "Chigiri", "Igaguri", "Kurona", "Hiori", "Gagamaru", "Bachira"],
    "Epic 🟣": ["Shidou", "Otoya", "Karasu", "Nagi", "Reo"],
    "Legendary 🟡": ["Shidou", "Otoya", "Karasu", "Nagi", "Reo"],
    "Mythic 🔴": ["Yukimiya", "NEL Bachira", "King", "Aiku", "Kunigami", "NEL Isagi"],
    "World Class ⚪️": ["Don Lorenzo", "Sae", "Kaiser", "NEL Rin", "NEL Nagi"],
    "OG 🟠": ["OG Aiku", "OG Sae", "OG Rin"],
}
RARITY_NAMES = list(RARITIES)
GK_BANNED_STYLES = {"Igaguri", "Aiku", "OG Aiku", "Don Lorenzo"}


def clean_style(style: str) -> str:
    return style.replace("OG ", "").strip()


@dataclass
class Player:
    member: discord.Member
    team: str
    position: str
    style: Optional[str] = None


class InhouseSession:
    def __init__(self, guild: discord.Guild, host_id: int):
        self.guild = guild
        self.host_id = host_id
        self.players: dict[int, Player] = {}
        self.message: Optional[discord.Message] = None
        self.ended = False
        self.started = False

    def all_players(self):
        return list(self.players.values())

    def team_players(self, team: str):
        return [p for p in self.players.values() if p.team == team]

    def open_teams(self, position: str):
        teams = [t for t in ("Home", "Away") if not any(p.team == t and p.position == position for p in self.players.values())]
        random.shuffle(teams)
        return teams

    def position_taken(self, position: str):
        return len([p for p in self.players.values() if p.position == position]) >= 2

    def style_allowed(self, player: Player, style: str, bypass: bool = False):
        if style == "Kaiser":
            return False, "هذا الستايل ممنوع حاليا!"
        if player.position == "GK" and style in GK_BANNED_STYLES:
            return False, "هذا الستايل ممنوع لمركزك!"
        if bypass or style == "Isagi":
            return True, ""
        same = [p for p in self.team_players(player.team) if p.style == style and p.member.id != player.member.id]
        if not same:
            return True, ""
        if len(same) == 1 and same[0].position == "GK":
            return True, ""
        if len(same) == 1 and player.position == "GK":
            return True, ""
        return False, "هذا الستايل مأخوذ بالفعل في فريقك!"

    def render(self):
        lines = ["# inhouse", "**", "", "> Home :"]
        for pos in POSITIONS:
            p = next((x for x in self.team_players("Home") if x.position == pos), None)
            value = "" if p is None else f"{p.member.mention} | {p.style or 'Choosing Style......'}"
            lines.append(f"> {pos} : {value}")
        lines += ["", "> Away :"]
        for pos in POSITIONS:
            p = next((x for x in self.team_players("Away") if x.position == pos), None)
            value = "" if p is None else f"{p.member.mention} | {p.style or 'Choosing Style......'}"
            lines.append(f"> {pos} : {value}")
        lines.append("**")
        if self.ended:
            lines.append("\n**Inhouse Ended**")
        elif self.started:
            lines.append("\n**Inhouse Started**")
        return "\n".join(lines)


# يمكن إنشاء أكثر من Inhouse في نفس السيرفر، وكل رسالة مرتبطة بجلسة مستقلة.
sessions: dict[int, list[InhouseSession]] = {}


def can_manage(interaction: discord.Interaction, session: InhouseSession):
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return member.id == session.host_id or member.guild_permissions.administrator or any(r.id == ALLOWED_ROLE_ID for r in member.roles)


def valid_channel(interaction: discord.Interaction):
    return interaction.channel_id in ALLOWED_CHANNEL_IDS


class PositionSelect(discord.ui.Select):
    def __init__(self, session: InhouseSession):
        self.session = session
        super().__init__(placeholder="Choose Your Position", options=[discord.SelectOption(label=p, value=p) for p in POSITIONS], custom_id="inhouse_position")

    async def callback(self, interaction: discord.Interaction):
        if self.session.ended:
            return await interaction.response.send_message("هذا الانهاوس منتهي!", ephemeral=True)
        if interaction.user.id in self.session.players:
            return await interaction.response.send_message("أنت مسجل بالفعل. استخدم Change Style أو Leave Position.", ephemeral=True)
        position = self.values[0]
        if self.session.position_taken(position):
            return await interaction.response.send_message("هذا المركز مأخوذ بالفعل!", ephemeral=True)
        teams = self.session.open_teams(position)
        if not teams:
            return await interaction.response.send_message("هذا المركز مأخوذ بالفعل!", ephemeral=True)
        member = interaction.user
        team = teams[0]
        player = Player(member=member, team=team, position=position)
        self.session.players[member.id] = player
        # اعرض اختيار الندرة مباشرة بعد حجز المركز بدون رسالة وسيطة.
        await interaction.response.send_message("Choose Your Rarity:", view=RarityView(self.session, member.id), ephemeral=True)
        await interaction.message.edit(content=self.session.render(), view=MainView(self.session))


class RaritySelect(discord.ui.Select):
    def __init__(self, session: InhouseSession, user_id: int, change: bool = False, bypass: bool = False):
        self.session, self.user_id, self.change, self.bypass = session, user_id, change, bypass
        options = [discord.SelectOption(label=name.split(" ")[0], description=name, value=name) for name in RARITY_NAMES]
        super().__init__(placeholder="Choose Rarity", options=options, custom_id=f"rarity_{user_id}_{change}_{bypass}")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id and not self.bypass:
            return await interaction.response.send_message("هذه القائمة ليست لك.", ephemeral=True)
        await interaction.response.edit_message(content="Choose Your Style:", view=StyleView(self.session, self.user_id, self.values[0], self.change, self.bypass))


class StyleSelect(discord.ui.Select):
    def __init__(self, session: InhouseSession, user_id: int, rarity: str, change: bool = False, bypass: bool = False):
        self.session, self.user_id, self.rarity, self.change, self.bypass = session, user_id, rarity, change, bypass
        opts = [discord.SelectOption(label=s, value=s) for s in RARITIES[rarity]]
        super().__init__(placeholder="Your Style?", options=opts, custom_id=f"style_{user_id}_{rarity}_{change}_{bypass}")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id and not self.bypass:
            return await interaction.response.send_message("هذه القائمة ليست لك.", ephemeral=True)
        player = self.session.players.get(self.user_id)
        if not player:
            return await interaction.response.send_message("اللاعب غير موجود في الانهاوس.", ephemeral=True)
        style = self.values[0]
        allowed, reason = self.session.style_allowed(player, style, self.bypass)
        if not allowed:
            return await interaction.response.send_message(reason, ephemeral=True)
        player.style = style
        await interaction.response.send_message(f"تم اختيار الستايل: {style}", ephemeral=True)
        if self.session.message:
            await self.session.message.edit(content=self.session.render(), view=MainView(self.session))


class PositionTargetSelect(discord.ui.Select):
    def __init__(self, session: InhouseSession, first_id: int):
        self.session, self.first_id = session, first_id
        source = session.players.get(first_id)
        options = []
        for team in ("Home", "Away"):
            for position in POSITIONS:
                occupant = next((p for p in session.all_players() if p.team == team and p.position == position and p.member.id != first_id), None)
                label = f"{team} {position}"
                description = "فارغ - نقل اللاعب هنا" if occupant is None else f"تبديل مع {occupant.member.display_name}"
                options.append(discord.SelectOption(label=label, description=description[:100], value=f"{team}|{position}"))
        super().__init__(placeholder="اختر الخانة الجديدة للاعب", options=options, custom_id=f"target_position_{first_id}")

    async def callback(self, interaction: discord.Interaction):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        source = self.session.players.get(self.first_id)
        if not source:
            return await interaction.response.send_message("اللاعب غير موجود.", ephemeral=True)
        target_team, target_position = self.values[0].split("|", 1)
        target = next((p for p in self.session.all_players() if p.team == target_team and p.position == target_position and p.member.id != self.first_id), None)
        old_team, old_position = source.team, source.position
        if target:
            target.team, target.position = old_team, old_position
        source.team, source.position = target_team, target_position
        action_text = "تم تبديل اللاعبين." if target else "تم نقل اللاعب إلى الخانة الجديدة."
        await interaction.response.edit_message(content=action_text, view=None)
        if self.session.message:
            await self.session.message.edit(content=self.session.render(), view=MainView(self.session))


class PlayerSelect(discord.ui.Select):
    def __init__(self, session: InhouseSession, action: str):
        self.session, self.action = session, action
        options = [discord.SelectOption(label=f"{p.member.display_name} - {p.position} ({p.team})", value=str(p.member.id)) for p in session.all_players()]
        super().__init__(placeholder="اختر لاعبًا", options=options[:25], custom_id=f"player_{action}")

    async def callback(self, interaction: discord.Interaction):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        uid = int(self.values[0])
        if self.action == "style":
            await interaction.response.edit_message(content="اختر الندرة:", view=RarityView(self.session, uid, change=True, bypass=True))
        else:
            await interaction.response.edit_message(content="اختر الخانة الجديدة للاعب:", view=PositionTargetView(self.session, uid))


class RarityView(discord.ui.View):
    def __init__(self, session, user_id, change=False, bypass=False):
        super().__init__(timeout=None)
        self.add_item(RaritySelect(session, user_id, change, bypass))


class StyleView(discord.ui.View):
    def __init__(self, session, user_id, rarity, change=False, bypass=False):
        super().__init__(timeout=None)
        self.add_item(StyleSelect(session, user_id, rarity, change, bypass))


class PositionTargetView(discord.ui.View):
    def __init__(self, session, first_id):
        super().__init__(timeout=None)
        self.add_item(PositionTargetSelect(session, first_id))


class HostView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Start Inhouse", style=discord.ButtonStyle.success, custom_id="host_start")
    async def start(self, interaction, button):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        await interaction.response.send_modal(StartModal(self.session))

    @discord.ui.button(label="Inhouse End", style=discord.ButtonStyle.danger, custom_id="host_end")
    async def end(self, interaction, button):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        self.session.ended = True
        await interaction.response.send_message("تم إنهاء الانهاوس وإغلاق جميع العمليات.", ephemeral=True)

    @discord.ui.button(label="Player Style", style=discord.ButtonStyle.success, custom_id="host_style")
    async def player_style(self, interaction, button):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        await interaction.response.send_message("اختر اللاعب:", view=PlayerView(self.session, "style"), ephemeral=True)

    @discord.ui.button(label="Player Position", style=discord.ButtonStyle.secondary, custom_id="host_position")
    async def player_position(self, interaction, button):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        await interaction.response.send_message("اختر اللاعب الأول:", view=PlayerView(self.session, "position"), ephemeral=True)


class PlayerView(discord.ui.View):
    def __init__(self, session, action):
        super().__init__(timeout=None)
        self.add_item(PlayerSelect(session, action))


class MainView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session
        self.add_item(PositionSelect(session))

    @discord.ui.button(label="Change Style", emoji="🔁", style=discord.ButtonStyle.primary, custom_id="change_style")
    async def change_style(self, interaction, button):
        if self.session.ended:
            return await interaction.response.send_message("هذا الانهاوس منتهي!", ephemeral=True)
        if interaction.user.id not in self.session.players:
            return await interaction.response.send_message("أنت غير مسجل.", ephemeral=True)
        await interaction.response.send_message("Change Your Style", view=RarityView(self.session, interaction.user.id, change=True), ephemeral=True)

    @discord.ui.button(label="Leave Position", emoji="🚪", style=discord.ButtonStyle.danger, custom_id="leave_position")
    async def leave(self, interaction, button):
        if self.session.ended:
            return await interaction.response.send_message("هذا الانهاوس منتهي!", ephemeral=True)
        if self.session.players.pop(interaction.user.id, None) is None:
            return await interaction.response.send_message("أنت غير مسجل.", ephemeral=True)
        await interaction.response.send_message("تم إخراجك من الانهاوس.", ephemeral=True)
        if self.session.message:
            await self.session.message.edit(content=self.session.render(), view=MainView(self.session))

    @discord.ui.button(label="Host Option", emoji="🗃️", style=discord.ButtonStyle.success, custom_id="host_option")
    async def host(self, interaction, button):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية لاستخدام خيارات المضيف.", ephemeral=True)
        await interaction.response.send_message("Host Option", view=HostView(self.session), ephemeral=True)


class StartModal(discord.ui.Modal, title="Start Inhouse"):
    message = discord.ui.TextInput(label="اكتب رسالة بداية الانهاوس", style=discord.TextStyle.paragraph, required=True, max_length=2000)

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage(interaction, self.session):
            return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
        self.session.started = True
        await interaction.response.send_message("تم بدء الانهاوس.", ephemeral=True)
        # أرسل رسالة البداية في الخاص لكل لاعب بدل إرسالها في روم الإنهاوس.
        dm_message = f"**Inhouse Started**\n{self.message.value}"
        for player in self.session.all_players():
            try:
                await player.member.send(dm_message)
            except (discord.Forbidden, discord.HTTPException):
                # إذا كانت رسائل الخاص مقفلة، لا نوقف إرسالها لبقية اللاعبين.
                continue
        if self.session.message:
            await self.session.message.edit(content=self.session.render(), view=MainView(self.session))


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


bot = Bot()


@bot.tree.command(name="inhouse", description="Create an Inhouse match")
async def inhouse(interaction: discord.Interaction):
    if not valid_channel(interaction):
        return await interaction.response.send_message("هذا الأمر غير مسموح في هذا الروم.", ephemeral=True)
    member = interaction.user
    if not isinstance(member, discord.Member):
        return await interaction.response.send_message("تعذر التحقق من العضو.", ephemeral=True)
    if not (member.guild_permissions.administrator or any(r.id == ALLOWED_ROLE_ID for r in member.roles)):
        return await interaction.response.send_message("ليس لديك صلاحية استخدام هذا الأمر.", ephemeral=True)
    session = InhouseSession(interaction.guild, member.id)
    sessions.setdefault(interaction.guild_id, []).append(session)
    await interaction.response.send_message(session.render(), view=MainView(session))
    session.message = await interaction.original_response()


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is missing")

bot.run(TOKEN)
