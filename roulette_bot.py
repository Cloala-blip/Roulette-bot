import discord
from discord.ext import commands
from discord.utils import get
import json
import os
import random

# ------------ CONFIG ------------
TOKEN = os.getenv("TOKEN")   # <-- REPLACES hard-coded token

PREFIX = "!"
CASHIER_ROLE_NAME = "Cashier"           # role that can add chips

# If you want to share chips with the blackjack bot,
# use the same CHIPS_FILE name and put both bots in the same folder.
CHIPS_FILE = "chips.json"


# ------------ BOT SETUP ------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

chips = {}  # user_id (str) -> int


# ------------ CHIP STORAGE HELPERS ------------

def load_chips():
    global chips
    if os.path.exists(CHIPS_FILE):
        with open(CHIPS_FILE, "r") as f:
            try:
                chips = json.load(f)
            except json.JSONDecodeError:
                chips = {}
    else:
        chips = {}


def save_chips():
    with open(CHIPS_FILE, "w") as f:
        json.dump(chips, f)


def get_balance(user_id: int) -> int:
    return chips.get(str(user_id), 0)


def change_balance(user_id: int, amount: int):
    uid = str(user_id)
    chips[uid] = chips.get(uid, 0) + amount
    if chips[uid] < 0:
        chips[uid] = 0
    save_chips()


# ------------ ROLE CHECK (CASHIER ONLY) ------------

def is_cashier():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        role = get(ctx.author.roles, name=CASHIER_ROLE_NAME)
        return role is not None
    return commands.check(predicate)


# ------------ ROULETTE LOGIC ------------

# European roulette numbers: 0–36
NUMBERS = list(range(0, 37))

# Red numbers in European roulette
RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}
BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS  # 1–36 minus reds; 0 is green


def spin_wheel() -> int:
    return random.choice(NUMBERS)


def get_color(number: int) -> str:
    if number == 0:
        return "green"
    elif number in RED_NUMBERS:
        return "red"
    else:
        return "black"


def evaluate_bet(number: int, bet: str) -> int:
    """
    Returns payout factor including the original bet.
    Example:
      0  -> lose (no payout)
      2  -> even-money win (1:1, returns 2x bet)
      3  -> 2:1 win (returns 3x bet)
      36 -> 35:1 win (returns 36x bet)
    """
    bet = bet.lower().strip()

    # Straight number bet
    if bet.isdigit():
        chosen = int(bet)
        if chosen == number:
            return 36  # 35:1 payout (36x including stake)
        else:
            return 0

    color = get_color(number)

    # Even / Odd (exclude 0)
    if bet == "even":
        if number != 0 and number % 2 == 0:
            return 2
        else:
            return 0
    if bet == "odd":
        if number != 0 and number % 2 == 1:
            return 2
        else:
            return 0

    # Red / Black
    if bet == "red":
        return 2 if color == "red" else 0
    if bet == "black":
        return 2 if color == "black" else 0

    # Low / High (1–18 / 19–36)
    if bet == "low":
        return 2 if 1 <= number <= 18 else 0
    if bet == "high":
        return 2 if 19 <= number <= 36 else 0

    # Dozens
    if bet == "1st12":
        return 3 if 1 <= number <= 12 else 0
    if bet == "2nd12":
        return 3 if 13 <= number <= 24 else 0
    if bet == "3rd12":
        return 3 if 25 <= number <= 36 else 0

    # Unknown bet type
    return 0


def format_roulette_result(number: int) -> str:
    color = get_color(number)
    if number == 0:
        return "**0** (green)"
    return f"**{number}** ({color})"


# ------------ EVENTS ------------

@bot.event
async def on_ready():
    load_chips()
    print(f"Logged in as {bot.user}")


# ------------ GENERAL COMMANDS ------------

@bot.command(name="balance")
async def balance_cmd(ctx):
    """Show your chip balance."""
    bal = get_balance(ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, you have **{bal}** chips.")


# ------------ CASHIER COMMANDS ------------

@bot.command(name="addchips")
@is_cashier()
async def addchips_cmd(ctx, member: discord.Member, amount: int):
    """Add chips to a user's account (Cashiers only)."""
    if amount <= 0:
        await ctx.send("Amount must be a positive integer.")
        return

    change_balance(member.id, amount)
    new_bal = get_balance(member.id)
    await ctx.send(
        f"✅ {ctx.author.mention} added **{amount}** chips to {member.mention}. "
        f"New balance: **{new_bal}** chips."
    )


@addchips_cmd.error
async def addchips_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You must have the **Cashier** role to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Usage: `!addchips @user <amount>` (amount must be an integer).")
    else:
        raise error


# ------------ ROULETTE COMMAND ------------

@bot.command(name="roulette")
async def roulette_cmd(ctx, *args):
    """
    Play roulette with one or more bets in a single spin.
    Usage:
      !roulette <amt1> <bet1> [<amt2> <bet2> ...]
    Examples:
      !roulette 10 red
      !roulette 10 red 5 17 20 odd
    """
    if len(args) < 2 or len(args) % 2 != 0:
        await ctx.send(
            "Usage: `!roulette <amount1> <bet1> [<amount2> <bet2> ...]`\n"
            "Example: `!roulette 10 red 5 17 20 odd`"
        )
        return

    # Parse pairs: (amount, bet)
    bets = []
    for i in range(0, len(args), 2):
        amount_str = args[i]
        bet_str = args[i + 1]

        # amount must be integer
        try:
            amount = int(amount_str)
        except ValueError:
            await ctx.send(f"Bet amount `{amount_str}` is not a valid integer.")
            return

        if amount <= 0:
            await ctx.send("Each bet amount must be a positive integer.")
            return

        bets.append((amount, bet_str))

    user_id = ctx.author.id
    balance = get_balance(user_id)
    total_stake = sum(a for a, _ in bets)

    if total_stake > balance:
        await ctx.send(
            f"{ctx.author.mention}, your total bet is **{total_stake}** chips, "
            f"but you only have **{balance}** chips."
        )
        return

    # Deduct the total stake once
    change_balance(user_id, -total_stake)

    # Spin the wheel once for all bets
    number = spin_wheel()
    result_text = format_roulette_result(number)

    total_payout = 0
    bet_lines = []

    for amount, bet in bets:
        factor = evaluate_bet(number, bet)
        if factor <= 0:
            # lost: stake already deducted as part of total_stake
            bet_lines.append(
                f"• **{amount}** on `{bet}` → ❌ loss (-{amount})"
            )
        else:
            payout = amount * factor  # includes original stake
            profit = payout - amount
            total_payout += payout
            bet_lines.append(
                f"• **{amount}** on `{bet}` → ✅ win! "
                f"Payout: **{payout}** (profit: **{profit}**)"
            )

    # Pay out winners (if any)
    if total_payout > 0:
        change_balance(user_id, total_payout)

    new_balance = get_balance(user_id)
    net_result = total_payout - total_stake

    if net_result > 0:
        summary = f"Overall result: ✅ You won **{net_result}** chips."
    elif net_result < 0:
        summary = f"Overall result: ❌ You lost **{-net_result}** chips."
    else:
        summary = "Overall result: 😐 You broke even."

    message = (
        f"🎡 The wheel spins...\n"
        f"Result: {result_text}\n\n"
        f"**Bet results:**\n"
        + "\n".join(bet_lines)
        + "\n\n"
        + summary
        + f"\nNew balance: **{new_balance}** chips."
    )

    await ctx.send(message)


@roulette_cmd.error
async def roulette_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "Usage: `!roulette <amount1> <bet1> [<amount2> <bet2> ...]`\n"
            "Example: `!roulette 10 red 5 17 20 odd`"
        )
    else:
        raise error


# ------------ CASHOUT COMMANDS ------------

@bot.command(name="cashout")
async def cashout_cmd(ctx, amount: int):
    """Cash out some chips and notify Cashiers."""
    if amount <= 0:
        await ctx.send("Cashout amount must be a positive integer.")
        return

    user_id = ctx.author.id
    current_bal = get_balance(user_id)

    if amount > current_bal:
        await ctx.send(
            f"{ctx.author.mention}, you only have **{current_bal}** chips. "
            f"You cannot cash out **{amount}**."
        )
        return

    change_balance(user_id, -amount)
    new_bal = get_balance(user_id)

    await ctx.send(
        f"💸 {ctx.author.mention}, you cashed out **{amount}** chips.\n"
        f"Remaining balance: **{new_bal}** chips.\n"
        f"Cashiers have been notified."
    )

    cashier_role = get(ctx.guild.roles, name=CASHIER_ROLE_NAME)
    if cashier_role is not None:
        await ctx.send(
            f"{cashier_role.mention} 💸 Cashout request:\n"
            f"User: {ctx.author} (`{ctx.author.id}`)\n"
            f"Amount: **{amount}** chips\n"
            f"Balance after cashout: **{new_bal}** chips."
        )


@bot.command(name="cashoutall")
async def cashoutall_cmd(ctx):
    """Cash out your entire balance and notify Cashiers."""
    user_id = ctx.author.id
    current_bal = get_balance(user_id)

    if current_bal <= 0:
        await ctx.send(f"{ctx.author.mention}, you have no chips to cash out.")
        return

    change_balance(user_id, -current_bal)

    cashier_role = get(ctx.guild.roles, name=CASHIER_ROLE_NAME)

    await ctx.send(
        f"💸 {ctx.author.mention}, you cashed out **{current_bal}** chips.\n"
        f"Your new balance is **0**.\n"
        f"Cashiers have been notified."
    )

    if cashier_role is not None:
        await ctx.send(
            f"{cashier_role.mention} 💸 Full cashout request:\n"
            f"User: {ctx.author} (`{ctx.author.id}`)\n"
            f"Amount: **{current_bal}** chips\n"
            f"Balance after cashout: **0** chips."
        )


# ------------ HELP / COMMANDS ------------

@bot.command(name="help")
async def help_cmd(ctx):
    """Show all commands for the roulette bot."""
    help_text = (
        "**🎰 Roulette Bot Commands**\n\n"
        "__**Player Commands**__\n"
        "`!balance` — Show your chip balance\n"
        "`!roulette <amt1> <bet1> [<amt2> <bet2> ...]` — One spin with multiple bets\n"
        "`!cashout <amount>` — Cash out some chips\n"
        "`!cashoutall` — Cash out ALL chips\n\n"
        "__**Roulette Bet Options**__\n"
        "`red`, `black`, `even`, `odd`, `low`, `high`\n"
        "`1st12`, `2nd12`, `3rd12` — Dozens\n"
        "`0`–`36` — Straight number bets\n\n"
        "__**Cashier Commands**__\n"
        "`!addchips @user <amount>` — Add chips to a player\n\n"
        "__**Notes**__\n"
        "• Only users with the **Cashier** role can use `!addchips`.\n"
        "• Players can only gain chips from wins or Cashier deposits.\n"
        "• `!commands` shows this list as well."
    )
    await ctx.send(help_text)


@bot.command(name="commands")
async def commands_cmd(ctx):
    """Alias for !help."""
    await help_cmd(ctx)


# ------------ RUN BOT ------------
if __name__ == "__main__":
    load_chips()
    bot.run(TOKEN)


