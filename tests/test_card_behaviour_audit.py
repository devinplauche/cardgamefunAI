"""Run tools/audit_card_behaviour.py as a test.

The tool drives all 55 cards through the real GameSession and compares the
measured state deltas against the printed text, per trigger point. It exists
because the two ally bugs of August 2026 had entirely correct card data and
were purely about *when* and *how often* effects fired - invisible to
tools/audit_cards.py (a text-vs-effects-dict lint) and to every unit test here.

Kept as a test, not just a script, because the failure mode it guards against
is a rules regression that no other check in this repo can see, and it runs in
well under a second.
"""

import unittest

from tools.audit_card_behaviour import BY_NAME, Finding, audit_card


def _run_audit():
    failures: list[Finding] = []
    unparsed: list[Finding] = []
    undrivable: list[tuple[str, str]] = []
    for card in sorted(BY_NAME.values(), key=lambda c: c.name):
        try:
            for finding in audit_card(card):
                (failures if finding.severity == "FAIL" else unparsed).append(finding)
        except Exception as exc:
            undrivable.append((card.name, f"{type(exc).__name__}: {exc}"))
    return failures, unparsed, undrivable


class TestCardBehaviourAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.failures, cls.unparsed, cls.undrivable = _run_audit()

    def test_no_card_behaves_differently_from_its_printed_text(self):
        detail = "\n".join(f"  {f.card}: {f.check} - {f.detail}" for f in self.failures)
        self.assertEqual(self.failures, [], f"\n{detail}")

    def test_every_card_can_be_driven_through_the_engine(self):
        """A card the harness cannot even play is an unaudited card."""
        detail = "\n".join(f"  {name}: {err}" for name, err in self.undrivable)
        self.assertEqual(self.undrivable, [], f"\n{detail}")

    def test_machine_checked_coverage_does_not_regress(self):
        """A ratchet, not a target.

        41 of 55 cards currently have every printed clause machine-checked; the
        rest state something the parser cannot reduce (mostly "you may
        sacrifice..." and the discard-pile manipulations). Lowering this means
        a clause stopped being checked - either a card changed or a handler
        broke - which is worth failing on rather than discovering later.
        """
        partial = {f.card for f in self.unparsed}
        covered = len(BY_NAME) - len(partial) - len(self.undrivable)
        self.assertGreaterEqual(
            covered, 41,
            f"machine-checked coverage dropped to {covered}/{len(BY_NAME)}; "
            f"cards with unparsed clauses: {sorted(partial)}",
        )


if __name__ == "__main__":
    unittest.main()
