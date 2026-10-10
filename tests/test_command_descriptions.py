"""Slash command descriptions: they fit Discord's limit and name the menu area they match."""
import re

from app import command_catalog as catalog, menu

DISCORD_LIMIT = 100
HOME_AREAS = ('work', 'craft', 'life', 'trade', 'community', 'me', 'help', 'mod')


def test_every_description_fits_discords_limit():
    too_long = {c['name']: len(c['description']) for c in catalog.commands if not 1 <= len(c['description']) <= DISCORD_LIMIT}
    assert not too_long


def test_no_description_still_says_colony_vote():
    assert not [c['name'] for c in catalog.commands if 'colony vote' in c['description'].lower()]


def test_every_registered_command_has_one_description_line():
    assert set(catalog.DESCRIPTIONS) == {c['name'] for c in catalog.commands}
    assert all(c['description'] == catalog.DESCRIPTIONS[c['name']] for c in catalog.commands)


def test_every_description_starts_with_a_menu_area():
    """The text before the first colon names an area on Home (or Home itself), so it follows the menu's names."""
    areas = {menu.AREAS[key][1] for key in HOME_AREAS} | {'Home'}
    named = re.compile(r'\b(?:' + '|'.join(re.escape(area) for area in areas) + r')\b')
    lost = [c['name'] for c in catalog.commands if not named.search(c['description'].split(':', 1)[0])]
    assert not lost
