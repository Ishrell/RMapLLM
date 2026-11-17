"""Relation inventory and domain lexicon.

Design rules (keep these when editing):
- Relation types are abstract and directed. No two types are converses of each
  other, so "x SUPPLY y" can never be re-read as "y <something> x".
- Every entity in a domain is a peer with a neutral name. Nothing about a name
  hints at who should be on which side of a relation.
- Each relation has three surface forms per domain: two active and one
  converse (tail mentioned first). Templates contain no periods and no
  gendered pronouns, and must be unambiguous within their domain.
"""

RELATIONS = {
    "AUTHORITY": "X directs or commands Y",
    "SUPPLY": "X provides goods or materials to Y",
    "TEACH": "X trains or instructs Y",
    "PROTECT": "X defends or shields Y",
    "EVALUATE": "X checks or judges Y's work",
    "OPPOSE": "X works against or harms Y",
}

# Sentence openers for every sentence after the first.
CONNECTIVES = ["", "", "Meanwhile, ", "In addition, ", "Also, "]

DOMAINS = {
    "office": {
        "heldout": False,
        "intros": ["At a mid-sized accounting firm,", "In the downtown office of a logistics company,"],
        "names": ["Maya", "Leo", "Noor", "Priya", "Tomas", "Ines", "Caleb", "Yuki", "Omar", "Dana"],
        "lex": {
            "AUTHORITY": ["{x} supervises {y}", "{x} manages {y}", "{y} reports to {x}"],
            "SUPPLY": ["{x} forwards client files to {y}", "{x} supplies {y} with the monthly figures", "{y} gets client files from {x}"],
            "TEACH": ["{x} trains {y} on the software", "{x} mentors {y}", "{y} is being trained by {x}"],
            "PROTECT": ["{x} covers for {y} when deadlines slip", "{x} shields {y} from angry clients", "{y} is shielded from complaints by {x}"],
            "EVALUATE": ["{x} audits {y}'s reports", "{x} reviews {y}'s work", "{y}'s work is reviewed by {x}"],
            "OPPOSE": ["{x} undermines {y} in meetings", "{x} files complaints against {y}", "{y} is regularly undermined by {x}"],
        },
    },
    "starship": {
        "heldout": False,
        "intros": ["Aboard the survey vessel Calypso,", "On a deep-space research ship,"],
        "names": ["Vex", "Tolo", "Aris", "Juno", "Kael", "Syra", "Dorn", "Mira", "Ebo", "Lune"],
        "lex": {
            "AUTHORITY": ["{x} commands {y}", "{x} gives orders to {y}", "{y} takes orders from {x}"],
            "SUPPLY": ["{x} routes power cells to {y}", "{x} delivers rations to {y}", "{y} receives power cells from {x}"],
            "TEACH": ["{x} instructs {y} in navigation", "{x} drills {y} on docking procedures", "{y} learns navigation from {x}"],
            "PROTECT": ["{x} guards {y} during spacewalks", "{x} shields {y} on away missions", "{y} is guarded by {x} on away missions"],
            "EVALUATE": ["{x} inspects {y}'s station", "{x} grades {y}'s flight logs", "{y}'s flight logs are checked by {x}"],
            "OPPOSE": ["{x} sabotages {y}'s experiments", "{x} jams {y}'s transmissions", "{y}'s experiments are sabotaged by {x}"],
        },
    },
    "school": {
        "heldout": False,
        "intros": ["In the robotics club at Ridgemont High,", "Among the students of a small-town science club,"],
        "names": ["Hana", "Diego", "Wren", "Amara", "Felix", "Sofia", "Jonah", "Lila", "Kofi", "Tessa"],
        "lex": {
            "AUTHORITY": ["{x} assigns tasks to {y}", "{x} is in charge of {y}", "{y} answers to {x}"],
            "SUPPLY": ["{x} lends notes to {y}", "{x} passes spare parts to {y}", "{y} borrows notes from {x}"],
            "TEACH": ["{x} tutors {y} in math", "{x} coaches {y} on soldering", "{y} is tutored by {x}"],
            "PROTECT": ["{x} stands up for {y} against bullies", "{x} defends {y} in arguments", "{y} is defended by {x}"],
            "EVALUATE": ["{x} checks {y}'s homework", "{x} judges {y}'s designs", "{y}'s designs are judged by {x}"],
            "OPPOSE": ["{x} spreads rumors about {y}", "{x} hides {y}'s tools", "{y} is teased by {x}"],
        },
    },
    "castle": {
        "heldout": False,
        "intros": ["In the court of a mountain kingdom,", "Within the walls of an old royal keep,"],
        "names": ["Aldric", "Maren", "Osric", "Elowen", "Bram", "Isolde", "Cedric", "Rowena", "Garrick", "Linnet"],
        "lex": {
            "AUTHORITY": ["{x} rules over {y}", "{x} gives commands to {y}", "{y} serves under {x}"],
            "SUPPLY": ["{x} sends grain to {y}", "{x} provides horses to {y}", "{y} receives grain from {x}"],
            "TEACH": ["{x} teaches swordsmanship to {y}", "{x} schools {y} in diplomacy", "{y} is taught swordsmanship by {x}"],
            "PROTECT": ["{x} guards {y}", "{x} defends {y}'s lands", "{y} is guarded by {x}"],
            "EVALUATE": ["{x} inspects {y}'s ledgers", "{x} judges {y}'s conduct", "{y}'s ledgers are inspected by {x}"],
            "OPPOSE": ["{x} plots against {y}", "{x} raids {y}'s storehouses", "{y} is the target of {x}'s plots"],
        },
    },
    "kitchen": {
        "heldout": False,
        "intros": ["In the kitchen of a busy bistro,", "Behind the counter of a harbor-side restaurant,"],
        "names": ["Remy", "Chiara", "Bao", "Anton", "Lucia", "Idris", "Greta", "Paolo", "Nia", "Sven"],
        "lex": {
            "AUTHORITY": ["{x} gives instructions to {y}", "{x} directs {y}", "{y} takes direction from {x}"],
            "SUPPLY": ["{x} hands prepped vegetables to {y}", "{x} supplies {y} with fresh stock", "{y} gets prepped ingredients from {x}"],
            "TEACH": ["{x} teaches knife skills to {y}", "{x} trains {y} on the grill", "{y} is learning sauces from {x}"],
            "PROTECT": ["{x} covers for {y} during the rush", "{x} takes the blame for {y}'s mistakes", "{y} is shielded from the owner's temper by {x}"],
            "EVALUATE": ["{x} tastes and scores {y}'s dishes", "{x} inspects {y}'s station", "{y}'s plates are checked by {x}"],
            "OPPOSE": ["{x} hides {y}'s knives", "{x} badmouths {y} to the owner", "{y} is badmouthed by {x}"],
        },
    },
    "hospital": {
        "heldout": False,
        "intros": ["On the night shift at a city hospital,", "In the surgical ward of a teaching hospital,"],
        "names": ["Farah", "Mateo", "Ingrid", "Kwame", "Elena", "Raj", "Signe", "Tariq", "Opal", "Hugo"],
        "lex": {
            "AUTHORITY": ["{x} oversees {y}", "{x} directs {y}'s rounds", "{y} answers to {x}"],
            "SUPPLY": ["{x} delivers lab samples to {y}", "{x} sends supplies to {y}", "{y} receives lab samples from {x}"],
            "TEACH": ["{x} trains {y} in suturing", "{x} teaches charting to {y}", "{y} is trained by {x}"],
            "PROTECT": ["{x} shields {y} from complaints", "{x} looks out for {y}", "{y} is looked after by {x}"],
            "EVALUATE": ["{x} reviews {y}'s charts", "{x} audits {y}'s prescriptions", "{y}'s charts are reviewed by {x}"],
            "OPPOSE": ["{x} blames {y} for errors", "{x} undercuts {y} in front of patients", "{y} is blamed for errors by {x}"],
        },
    },
    "pirates": {
        "heldout": False,
        "intros": ["Aboard the pirate sloop Marigold,", "Among the crew of a smuggling brig,"],
        "names": ["Flint", "Anne", "Barlow", "Corwin", "Mags", "Tobias", "Pell", "Rosa", "Jib", "Ned"],
        "lex": {
            "AUTHORITY": ["{x} gives orders to {y}", "{x} commands {y}", "{y} obeys {x}"],
            "SUPPLY": ["{x} hands gunpowder to {y}", "{x} passes rations to {y}", "{y} gets gunpowder from {x}"],
            "TEACH": ["{x} teaches knots to {y}", "{x} trains {y} to navigate by the stars", "{y} learns knots from {x}"],
            "PROTECT": ["{x} watches {y}'s back in a fight", "{x} defends {y} during boarding raids", "{y} is defended by {x} in every fight"],
            "EVALUATE": ["{x} inspects {y}'s rigging work", "{x} checks {y}'s tallies", "{y}'s rigging work is inspected by {x}"],
            "OPPOSE": ["{x} steals from {y}", "{x} schemes against {y}", "{y} is cheated at dice by {x}"],
        },
    },
    "robots": {
        "heldout": True,
        "intros": ["In an automated warehouse run by robots,", "On the floor of a robot-operated sorting plant,"],
        "names": ["Bolt", "Pixel", "Gizmo", "Tread", "Servo", "Nano", "Cog", "Rivet", "Diode", "Flux"],
        "lex": {
            "AUTHORITY": ["{x} issues directives to {y}", "{x} controls {y}'s task queue", "{y} executes directives from {x}"],
            "SUPPLY": ["{x} transfers battery packs to {y}", "{x} feeds parts to {y}", "{y} receives battery packs from {x}"],
            "TEACH": ["{x} teaches routing skills to {y}", "{x} trains {y} to sort packages", "{y} learns sorting from {x}"],
            "PROTECT": ["{x} shields {y} from collisions", "{x} guards {y} during recharging", "{y} is guarded by {x} during recharging"],
            "EVALUATE": ["{x} runs diagnostics on {y}", "{x} verifies {y}'s output", "{y}'s output is verified by {x}"],
            "OPPOSE": ["{x} blocks {y}'s path", "{x} corrupts {y}'s logs", "{y}'s logs are corrupted by {x}"],
        },
    },
    "theater": {
        "heldout": True,
        "intros": ["In a touring theater troupe,", "Backstage at a small repertory company,"],
        "names": ["Beatrix", "Lorenzo", "Odette", "Marcel", "Viola", "Ansel", "Colette", "Dmitri", "Fern", "Jasper"],
        "lex": {
            "AUTHORITY": ["{x} gives stage directions to {y}", "{x} directs {y}", "{y} takes direction from {x}"],
            "SUPPLY": ["{x} hands costumes to {y}", "{x} provides props to {y}", "{y} gets costumes from {x}"],
            "TEACH": ["{x} coaches {y} on delivery", "{x} teaches stage combat to {y}", "{y} learns stage combat from {x}"],
            "PROTECT": ["{x} defends {y} against harsh critics", "{x} covers for {y} when lines are forgotten", "{y} is defended by {x} against critics"],
            "EVALUATE": ["{x} critiques {y}'s performances", "{x} reviews {y}'s rehearsals", "{y}'s performances are critiqued by {x}"],
            "OPPOSE": ["{x} upstages {y}", "{x} mocks {y} backstage", "{y} is mocked backstage by {x}"],
        },
    },
}

FAMILIAR_DOMAINS = [d for d, v in DOMAINS.items() if not v["heldout"]]
HELDOUT_DOMAINS = [d for d, v in DOMAINS.items() if v["heldout"]]
