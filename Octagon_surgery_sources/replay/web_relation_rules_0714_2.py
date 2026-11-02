"""Compatibility alias for the current relation-rule implementation."""

import web_relation_rules_optimized_20260726 as _impl
from web_relation_rules_optimized_20260726 import *  # noqa: F401,F403

# Keep the stable API used by the 0714 engine and website explicit. This also
# protects the compatibility module if the implementation later defines
# ``__all__`` and omits one of these entry points.
detect_gppss_figure43_four_cycles = _impl.detect_gppss_figure43_four_cycles
detect_sl4_lemma48_zero_pair = _impl.detect_sl4_lemma48_zero_pair
detect_sl4_lemma49_zero_pair = _impl.detect_sl4_lemma49_zero_pair
lemma49_rule_catalog = _impl.lemma49_rule_catalog
sl4_lemma48_zero_rule_catalog = _impl.sl4_lemma48_zero_rule_catalog
sl4_lemma49_zero_rule_catalog = _impl.sl4_lemma49_zero_rule_catalog
