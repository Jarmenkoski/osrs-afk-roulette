# OSRS AFK-ruletti 🎡

Staattinen sivu, joka arpoo päivän AFK-tehtävän Old School RuneScapeen — rulettipyörällä.

**Live**: https://jarmenkoski.github.io/osrs-afk-roulette/

## Miten toimii

1. Syötä OSRS-nimimerkki → levelit haetaan [Wise Old Man](https://wiseoldman.net) -APIsta (fallback: virallinen hiscores CORS-proxyn läpi).
2. Tehtäväpankki ([tasks.js](tasks.js)) on kuratoitu [OSRS Wikin AFK-listasta](https://oldschool.runescape.wiki/w/Guide:AFK_Skilling_Methods) — vain tehtävät, joiden skill-vaatimukset täyttyvät, pääsevät pyörään.
3. **Generoi** → rulettipyörä pyörii ja pysähtyy päivän tehtävään.
4. Tuloksen voi postata Discord-kanavalle webhookilla (⚙️-asetuksista; URL tallentuu vain selaimen localStorageen, ei repoon).

## Discord-webhookin luonti

Discordissa: Kanavan asetukset → Integraatiot → Webhookit → Uusi webhook → Kopioi URL → liitä sivun ⚙️-asetuksiin.

Ei buildia, ei backendiä — pelkkä HTML/CSS/JS, hostattu GitHub Pagesissa.
