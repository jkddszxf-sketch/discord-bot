import asyncio
import os
import random
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLE_ID = 1566790917107490877
ALLOWED_CHANNEL_IDS = {1571149166623592498, 1571136783029379202}
WELCOME_CHANNEL_ID = 1566084702576836678
VERIFY_CHANNEL_ID = 1572225298290974822
UNVERIFIED_ROLE_ID = 1572638003724030075
VERIFIED_ROLE_ID = 1571923838210412644
WELCOME_GIF_URL = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663438813915/qRAGTlswHRnfofRj.gif"
BOT_COLOR = discord.Color.from_str("#0d8f00")

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


# ------------------------- Community systems -------------------------
def is_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id == ALLOWED_ROLE_ID for r in member.roles)


def color_from_hex(value: str) -> discord.Color:
    value = value.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return BOT_COLOR
    return discord.Color(int(value, 16))


def welcome_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="WELCOME 👋🏻",
        description=f"**Welcome To Middle East Rankings {member.mention} !**\n\n**・Be respectful**\n**・Read the rules**\n**・Have fun and enjoy**",
        color=BOT_COLOR,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if WELCOME_GIF_URL:
        embed.set_image(url=WELCOME_GIF_URL)
    return embed


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="verify", emoji="✅", style=discord.ButtonStyle.success, custom_id="verify_member")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("تعذر التحقق من العضو.", ephemeral=True)
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
        old_role, new_role = guild.get_role(UNVERIFIED_ROLE_ID), guild.get_role(VERIFIED_ROLE_ID)
        try:
            if old_role:
                await interaction.user.remove_roles(old_role, reason="Member verification")
            if new_role:
                await interaction.user.add_roles(new_role, reason="Member verification")
        except discord.Forbidden:
            return await interaction.response.send_message("البوت لا يملك صلاحية إدارة الرتب.", ephemeral=True)
        await interaction.response.send_message("تم التحقق بنجاح ✅", ephemeral=True)


def verify_embed() -> discord.Embed:
    embed = discord.Embed(
        description="This server requires you to verify yourself to get access to other channels, you can simply verify by completing a captcha, click on the button below",
        color=BOT_COLOR,
    )
    if WELCOME_GIF_URL:
        embed.set_image(url=WELCOME_GIF_URL)
    return embed


class EphemeralButton(discord.ui.View):
    def __init__(self, response: str, image_url: str = ""):
        super().__init__(timeout=None)
        self.response_text = response
        self.image_url = image_url

    @discord.ui.button(label="اضغط هنا", style=discord.ButtonStyle.primary, custom_id="custom_ephemeral_button")
    async def click(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(description=self.response_text, color=BOT_COLOR) if self.image_url else None
        if embed:
            embed.set_image(url=self.image_url)
        await interaction.response.send_message(self.response_text if not embed else None, embed=embed, ephemeral=True)


giveaways: dict[int, dict] = {}


def parse_giveaway_duration(value: str) -> tuple[int, str]:
    normalized = value.strip().lower()
    replacements = {
        "دقيقة": "m", "دقائق": "m", "دقيقه": "m",
        "ساعة": "h", "ساعات": "h", "ساعه": "h",
        "يوم": "d", "أيام": "d", "ايام": "d",
        "أسبوع": "w", "اسبوع": "w", "أسابيع": "w", "اسابيع": "w",
    }
    for word, unit in replacements.items():
        normalized = normalized.replace(word, unit)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|h|d|w)", normalized)
    if not match:
        raise ValueError("استخدم صيغة مثل 10m أو 2h أو 1d أو 1w")
    amount, unit = float(match.group(1)), match.group(2)
    seconds = int(amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit])
    return max(seconds, 60), unit


def remaining_text(seconds: float) -> str:
    # Discord-style countdown: one hour starts as 59m, then 58m, etc.
    seconds = max(0, int(seconds) - 1)
    if seconds <= 0:
        return "ago"
    if seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    return f"{max(1, seconds // 60)}m"


def giveaway_embed(data: dict, ended: bool = False) -> discord.Embed:
    if ended:
        time_text = "ago"
    else:
        time_text = remaining_text(data["ends_at"] - datetime.now(timezone.utc).timestamp())
    embed = discord.Embed(title="Giveaway 🎉", color=BOT_COLOR)
    embed.description = (
        f"- Prize: {data['prize']}\n"
        f"- Number of Winners: {data['winner_count']}\n"
        f"- Participants: {len(data['entries'])}\n"
        f"- Time Remaining: {time_text}"
    )
    return embed


async def update_giveaway_message(message: discord.Message, data: dict, ended: bool = False):
    await message.edit(embed=giveaway_embed(data, ended=ended), view=None if ended else GiveawayView())


class GiveawayView(discord.ui.View):
    def __init__(self, message_id: int | None = None):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="Enter Giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways.get(interaction.message.id)
        if not giveaway or giveaway["ended"]:
            return await interaction.response.send_message("هذا القيف أواي انتهى.", ephemeral=True)
        entries: set[int] = giveaway["entries"]
        if interaction.user.id in entries:
            entries.remove(interaction.user.id)
            text = "تم إلغاء دخولك من القيف أواي."
        else:
            entries.add(interaction.user.id)
            text = "تم تسجيل دخولك في القيف أواي 🎉"
        await interaction.response.send_message(text, ephemeral=True)
        await update_giveaway_message(interaction.message, giveaway)


async def finish_giveaway(message: discord.Message):
    giveaway = giveaways.get(message.id)
    if not giveaway:
        return
    while True:
        remaining = giveaway["ends_at"] - datetime.now(timezone.utc).timestamp()
        if remaining <= 0:
            break
        await asyncio.sleep(min(60, max(1, remaining)))
        if giveaway["ended"]:
            return
        try:
            await update_giveaway_message(message, giveaway)
        except discord.HTTPException:
            pass
    giveaway["ended"] = True
    guild = message.guild
    members = [guild.get_member(uid) for uid in giveaway["entries"]] if guild else []
    members = [m for m in members if m]
    winners = random.sample(members, min(giveaway["winner_count"], len(members))) if members else []
    giveaway["winners"] = [m.id for m in winners]
    await update_giveaway_message(message, giveaway, ended=True)
    mentions = ", ".join(m.mention for m in winners) or "لا يوجد فائزون"
    await message.channel.send(f"🎉 Giveaway ended!\n**Prize:** {giveaway['prize']}\n**Winners:** {mentions}")


TICKET_TYPES = {
    "referee": {"label": "Referee", "emoji": "Referee", "description": "Contact a referee directly for assistanc", "role_id": 1573783168555942211},
    "pc_check": {"label": "Pc Check", "emoji": "pc_check", "description": "Request a PC check for suspected cheats", "role_id": 1573783241708806305},
    "forced": {"label": "Forced", "emoji": "🔒", "description": "Force a team to play after repeated requests", "role_id": 1573783320180035664},
    "higher_up": {"label": "Higher Up", "emoji": "Owners1", "description": "Contact the Higher Ups for server issues", "role_id": 1566808256771391588},
}


def ticket_emoji(guild: discord.Guild, name: str, fallback: str = "🎫"):
    if len(name) <= 2:
        return name
    emoji = discord.utils.find(lambda e: e.name == name, guild.emojis)
    return emoji or fallback


def ticket_info(channel: discord.TextChannel) -> dict:
    values = {}
    for part in (channel.topic or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            values[key] = value
    return values


def ticket_manager(interaction: discord.Interaction, channel: discord.TextChannel) -> bool:
    info = ticket_info(channel)
    role_id = int(info.get("role", 0)) if info.get("role", "").isdigit() else 0
    return isinstance(interaction.user, discord.Member) and (interaction.user.guild_permissions.administrator or any(r.id == role_id for r in interaction.user.roles))


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild):
        options = []
        for key, value in TICKET_TYPES.items():
            emoji = ticket_emoji(guild, value["emoji"], "🎫")
            options.append(discord.SelectOption(label=value["label"], value=key, description=value["description"], emoji=emoji))
        super().__init__(placeholder="Select Ticket Type", options=options, custom_id="ticket_type_select")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
        key = self.values[0]
        data = TICKET_TYPES[key]
        existing = next((c for c in guild.text_channels if c.name == f"ticket-{interaction.user.name.lower()}"[:95]), None)
        if existing:
            return await interaction.response.send_message(f"لديك تكت مفتوح: {existing.mention}", ephemeral=True)
        category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
        role = guild.get_role(data["role_id"])
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
        }
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}"[:95], category=category, overwrites=overwrites, topic=f"owner={interaction.user.id};role={data['role_id']};type={key}", reason="Ticket opened")
        embed = discord.Embed(description=f"{interaction.user.mention} | {data['label']} Ticket\n\nPlease wait, and we will respond as soon as possible.\n\n{role.mention if role else ''}\n\n2026/21/11 10:52PM", color=BOT_COLOR)
        embed.set_image(url=WELCOME_GIF_URL)
        await channel.send(embed=embed, view=TicketToolsView())
        await interaction.response.send_message(f"تم فتح التذكرة: {channel.mention}", ephemeral=True)


class TicketSetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect(guild))


class RenameTicketModal(discord.ui.Modal, title="Rename Ticket"):
    name = discord.ui.TextInput(label="الاسم الجديد", max_length=80, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel) or not ticket_manager(interaction, interaction.channel):
            return await interaction.response.send_message("ليس لديك الصلاحية.", ephemeral=True)
        await interaction.channel.edit(name=f"ticket-{self.name.value.lower().replace(' ', '-')}")
        await interaction.response.send_message("تم تغيير اسم التذكرة.", ephemeral=True)


class TicketMemberSelect(discord.ui.UserSelect):
    def __init__(self, action: str):
        self.action = action
        super().__init__(placeholder="اختر العضو", min_values=1, max_values=1, custom_id=f"ticket_member_{action}")

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not ticket_manager(interaction, channel):
            return await interaction.response.send_message("ليس لديك الصلاحية.", ephemeral=True)
        member = self.values[0]
        if self.action == "add":
            await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            text = f"تمت إضافة {member.mention} إلى التذكرة."
        else:
            await channel.set_permissions(member, overwrite=None)
            text = f"تمت إزالة {member.mention} من التذكرة."
        await interaction.response.send_message(text, ephemeral=True)


class TicketMemberView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=120)
        self.add_item(TicketMemberSelect(action))


class TicketToolsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="خيارات التذكرة", emoji="⚙️", style=discord.ButtonStyle.success, custom_id="ticket_options")
    async def options(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.TextChannel) or not ticket_manager(interaction, interaction.channel):
            return await interaction.response.send_message("ليس لديك الصلاحية", ephemeral=True)
        await interaction.response.send_message("اختر أحد خيارات إدارة التذكرة:", view=TicketOptionsView(), ephemeral=True)

    @discord.ui.button(label="إغلاق التذكرة", emoji="❌", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.TextChannel) or not ticket_manager(interaction, interaction.channel):
            return await interaction.response.send_message("ليس لديك الصلاحية", ephemeral=True)
        await interaction.response.send_message("سيتم إغلاق التذكرة بعد 3 ثوانٍ.")
        await asyncio.sleep(3)
        await interaction.channel.delete(reason="Ticket closed")


class TicketOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="تغيير اسم التذكرة", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RenameTicketModal())

    @discord.ui.button(label="إضافة عضو", emoji="➕", style=discord.ButtonStyle.success)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر العضو:", view=TicketMemberView("add"), ephemeral=True)

    @discord.ui.button(label="إزالة عضو", emoji="➖", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("اختر العضو:", view=TicketMemberView("remove"), ephemeral=True)

    @discord.ui.button(label="إيقاف صلاحية الرسائل", emoji="🔇", style=discord.ButtonStyle.danger)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not ticket_manager(interaction, channel):
            return await interaction.response.send_message("ليس لديك الصلاحية", ephemeral=True)
        for target, overwrite in list(channel.overwrites.items()):
            if isinstance(target, (discord.Member, discord.Role)) and target != interaction.guild.me:
                overwrite.send_messages = False
                await channel.set_permissions(target, overwrite=overwrite)
        await channel.set_permissions(interaction.user, send_messages=True)
        await interaction.response.send_message("تم إيقاف صلاحية الكتابة.", ephemeral=True)


class PollView(discord.ui.View):
    def __init__(self, options: list[str]):
        super().__init__(timeout=None)
        self.votes: dict[int, int] = {}
        self.options = options
        for index, option in enumerate(options):
            button = discord.ui.Button(label=option[:80], emoji=f"{index + 1}️⃣", style=discord.ButtonStyle.primary, custom_id=f"poll_{index}")
            async def callback(interaction: discord.Interaction, i=index):
                self.votes[interaction.user.id] = i
                await interaction.response.send_message(f"تم تسجيل تصويتك لـ **{self.options[i]}**", ephemeral=True)
            button.callback = callback
            self.add_item(button)


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        self.guild_commands_synced = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(VerifyView())
        self.add_view(TicketToolsView())

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        # Global slash commands can take time to propagate. Copy them to each
        # connected guild so new commands appear immediately in the server.
        if not self.guild_commands_synced:
            for guild in self.guilds:
                try:
                    self.add_view(TicketSetupView(guild))
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                    print(f"Synced slash commands to {guild.name} ({guild.id})")
                except discord.HTTPException as error:
                    print(f"Could not sync commands to {guild.id}: {error}")
            # Remove old global copies so each command appears once only.
            self.tree.clear_commands(guild=None)
            try:
                await self.tree.sync()
                print("Removed old global slash-command copies")
            except discord.HTTPException as error:
                print(f"Could not clear global commands: {error}")
            self.guild_commands_synced = True


bot = Bot()


def staff_only(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and is_staff(interaction.user)


@bot.event
async def on_member_join(member: discord.Member):
    unverified = member.guild.get_role(UNVERIFIED_ROLE_ID)
    if unverified:
        try:
            await member.add_roles(unverified, reason="New member verification")
        except discord.Forbidden:
            pass
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=welcome_embed(member))


@bot.tree.command(name="setup_verify", description="Send or refresh the verification panel")
async def setup_verify(interaction: discord.Interaction):
    if not staff_only(interaction):
        return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
    channel = interaction.guild.get_channel(VERIFY_CHANNEL_ID) if interaction.guild else None
    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message("لم أجد روم التحقق.", ephemeral=True)
    await channel.send(embed=verify_embed(), view=VerifyView())
    await interaction.response.send_message("تم إرسال لوحة التحقق.", ephemeral=True)


@bot.tree.command(name="say", description="Send a customizable bot message")
@app_commands.describe(content="النص العادي", title="عنوان Embed اختياري", description="وصف Embed اختياري", color="لون HEX مثل 0d8f00", image_url="رابط صورة اختياري", button_label="اسم زر اختياري", button_response="رسالة الزر المخفية", button_image_url="صورة داخل الرسالة المخفية")
async def say(interaction: discord.Interaction, content: str = "", title: str = "", description: str = "", color: str = "0d8f00", image_url: str = "", button_label: str = "", button_response: str = "", button_image_url: str = ""):
    if not staff_only(interaction):
        return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
    embed = None
    if title or description or image_url:
        embed = discord.Embed(title=title or None, description=description or None, color=color_from_hex(color))
        if image_url:
            embed.set_image(url=image_url)
    view = EphemeralButton(button_response, button_image_url) if button_label and button_response else None
    if view:
        view.children[0].label = button_label[:80]
    await interaction.channel.send(content=content or None, embed=embed, view=view)
    await interaction.response.send_message("تم إرسال الرسالة.", ephemeral=True)


@bot.tree.command(name="giveaway", description="Create a giveaway")
@app_commands.describe(duration="المدة مثل 30m أو 2h أو 1d أو 1w", winners="عدد الفائزين", prize="الجائزة")
async def giveaway(interaction: discord.Interaction, duration: str, winners: app_commands.Range[int, 1, 20], prize: str):
    if not staff_only(interaction):
        return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
    try:
        duration_seconds, _ = parse_giveaway_duration(duration)
    except ValueError as error:
        return await interaction.response.send_message(str(error), ephemeral=True)
    giveaway_data = {"entries": set(), "winner_count": winners, "prize": prize, "ends_at": datetime.now(timezone.utc).timestamp() + duration_seconds, "ended": False, "channel_id": interaction.channel_id}
    embed = giveaway_embed(giveaway_data)
    await interaction.response.send_message("تم إنشاء القيف أواي.", ephemeral=True)
    message = await interaction.channel.send(embed=embed, view=GiveawayView())
    giveaways[message.id] = giveaway_data
    asyncio.create_task(finish_giveaway(message))


@bot.tree.command(name="giveaway_reroll", description="Choose a new giveaway winner")
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    if not staff_only(interaction):
        return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
    giveaway_data = giveaways.get(int(message_id))
    if not giveaway_data or not giveaway_data["ended"]:
        return await interaction.response.send_message("القيف أواي غير موجود أو لم ينتهِ.", ephemeral=True)
    members = [interaction.guild.get_member(uid) for uid in giveaway_data["entries"]]
    members = [m for m in members if m]
    if not members:
        return await interaction.response.send_message("لا يوجد مشاركون.", ephemeral=True)
    winner = random.choice(members)
    await interaction.channel.send(f"🔁 الفائز الجديد في **{giveaway_data['prize']}** هو {winner.mention}!")
    await interaction.response.send_message("تم تغيير الفائز.", ephemeral=True)


@bot.tree.command(name="set_up_tickets", description="Send the ME Tickets panel")
async def set_up_tickets(interaction: discord.Interaction):
    if not staff_only(interaction):
        return await interaction.response.send_message("ليس لديك صلاحية.", ephemeral=True)
    if not interaction.guild:
        return await interaction.response.send_message("هذا الأمر داخل السيرفر فقط.", ephemeral=True)
    embed = discord.Embed(
        title=":ticket~2: ME TICKETS",
        description=(
            "———————————————\n"
            ":Referee: **Referee Ticket :**\n"
            ":51047animatedarrowwhite: Contact a referee directly for assistanc\n\n"
            "———————————————\n"
            ":pc_check: **Pc Check Ticket :**\n"
            ":51047animatedarrowwhite: Request a PC check for suspected cheats\n\n"
            "———————————————\n"
            "🔒 **Forced Ticket**\n"
            ":51047animatedarrowwhite: Force a team to play after repeated requests\n\n"
            "———————————————\n"
            ":Owners1: **Higher Up Ticket**\n"
            ":51047animatedarrowwhite: Contact the Higher Ups for server issues"
        ),
        color=BOT_COLOR,
    )
    embed.set_image(url=WELCOME_GIF_URL)
    await interaction.channel.send(embed=embed, view=TicketSetupView(interaction.guild))
    await interaction.response.send_message("تم إرسال لوحة التذاكر.", ephemeral=True)


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
