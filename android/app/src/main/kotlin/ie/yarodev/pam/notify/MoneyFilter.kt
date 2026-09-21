package ie.yarodev.pam.notify

/**
 * Whether a notification could possibly be about money.
 *
 * This is the only judgement the phone makes. It is deliberately crude: a
 * number next to a currency marker. Everything else — is it a payment, which
 * way did the money go, what shop, what category — is the server's job.
 *
 * Crude on purpose, because this is a privacy boundary. The listener sees
 * every notification on the device, including messages, and only the ones
 * that pass here ever leave it. A rule small enough to read in one sitting is
 * a rule you can trust with that.
 *
 * The same expression lives in app/services/notifications.py and is applied
 * again server-side; if you change one, change both.
 */
object MoneyFilter {

    private const val AMOUNT = """\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{2})?"""

    private val LOOKS_LIKE_MONEY = Regex(
        """(?:[€$£₴]\s*$AMOUNT)|(?:$AMOUNT\s*(?:[€$£₴]|eur|euro|usd|gbp|ron|lei|pln|uah|грн))""",
        RegexOption.IGNORE_CASE,
    )

    fun couldBeMoney(text: String): Boolean = LOOKS_LIKE_MONEY.containsMatchIn(text)
}
