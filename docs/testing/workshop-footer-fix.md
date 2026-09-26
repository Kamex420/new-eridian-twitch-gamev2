# Workshop dispatch and Discord footer

The signed Discord interactions endpoint rejected /workshop before reaching its existing handler because the command was absent from the accepted command sets. It is now accepted as a private command. Station access checks, tier requirements, and prices are unchanged.

Compact message rendering now retains the footer “New Eridian v2 • May Rocky's wisdom guide you.” on short cards, queue cards, and overview/detail pages. The in-game society remains New Eridian.

## Validation

74 focused tests passed across test_workshop_discord_footer.py, test_message_layout.py, test_crafting_progression.py, and test_discord_deferred.py. Coverage includes signed workshop unlock delivery, exactly one charge for a repeated interaction, registration-to-endpoint command coverage, and footers on compact and paginated replies. Two dependency deprecation warnings remain. Discord delivery was mocked; this patch has not been deployed to Railway. Whitespace checks passed.
