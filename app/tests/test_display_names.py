"""professional_name — display-grade casing for stored master-data names.

The user writes "motorbike" in a conversation; the catalogue must store
"Motorbike" (industry-grade hierarchy per the owner's directive), while
casing the user set deliberately — acronyms, mixed-case brands — survives
untouched.
"""

from app.display_names import professional_name


class TestLowercaseWordsGetCapitalised:
    def test_single_word(self):
        assert professional_name("motorbike") == "Motorbike"

    def test_plural_from_request(self):
        assert professional_name("motorbikes") == "Motorbikes"

    def test_multi_word_sentence_case(self):
        assert professional_name("motorbikes for sale") == "Motorbikes for Sale"

    def test_connectors_stay_lowercase_mid_name(self):
        assert professional_name("john and sons") == "John and Sons"
        assert professional_name("office of acme") == "Office of Acme"

    def test_first_word_is_capitalised_even_if_a_connector(self):
        assert professional_name("the office") == "The Office"

    def test_apostrophes_and_hyphens(self):
        assert professional_name("don't panic") == "Don't Panic"
        assert professional_name("al-areesh engineering") == "Al-Areesh Engineering"


class TestCaseTheUserSetIsPreserved:
    def test_acronyms_survive(self):
        assert professional_name("ABC Autos") == "ABC Autos"
        assert professional_name("Zameer Labs PVT Ltd") == "Zameer Labs PVT Ltd"

    def test_mixed_case_brands_survive(self):
        assert professional_name("iPhone") == "iPhone"
        assert professional_name("Al-Areesh Engineering") == "Al-Areesh Engineering"

    def test_already_title_cased_is_a_noop(self):
        assert professional_name("Motorbike") == "Motorbike"
        assert professional_name("Acme Engineering") == "Acme Engineering"


class TestStructureIsPreserved:
    def test_digits_untouched(self):
        assert professional_name("45000 laptops") == "45000 Laptops"

    def test_whitespace_collapses_and_trims(self):
        assert professional_name("  acme   motors  ") == "Acme Motors"


class TestEmptyInputs:
    def test_none_and_empty_stay_empty(self):
        assert professional_name(None) == ""
        assert professional_name("") == ""
        assert professional_name("   ") == ""
