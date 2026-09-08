from flashcards.importer import _is_machine_field, _selected_fields, _template_fields, field_to_html


def test_template_fields_understands_anki_filters_and_conditionals():
    template = "{{#Back}}{{text:Back}}{{/Back}} {{hint:Mnemonic}} {{FrontSide}}"

    assert _template_fields(template) == ["Back", "Mnemonic"]


def test_selected_fields_excludes_hidden_metadata_from_answer():
    model = {
        "type": 0,
        "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "SourceData"}],
        "tmpls": [{"qfmt": "{{Front}}", "afmt": "{{FrontSide}}<hr>{{Back}}"}],
    }

    front, back = _selected_fields(
        ["Question", "Answer", "{huge metadata and file structure}"], model, 0
    )

    assert front == ["Question"]
    assert back == ["Answer"]


def test_selected_fields_uses_the_requested_reversed_card_template():
    model = {
        "type": 0,
        "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "Internal"}],
        "tmpls": [
            {"qfmt": "{{Front}}", "afmt": "{{FrontSide}}{{Back}}"},
            {"qfmt": "{{Back}}", "afmt": "{{FrontSide}}{{Front}}"},
        ],
    }

    assert _selected_fields(["Question", "Answer", "trash"], model, 1) == (
        ["Answer"],
        ["Question"],
    )


def test_scripted_template_payloads_are_not_visible_card_fields():
    assert _is_machine_field("concept::c6d7c4072004837a56b5")
    assert _is_machine_field(
        "W3sib3JpZ2luYWxfbGFiZWwiOiJBIiwidGV4dCI6IkFuc3dlciIsImlzX2NvcnJlY3QiOnRydWV9XQ=="
    )
    assert _is_machine_field("Course::Year 2::Microbiology::Lecture 1")
    assert _is_machine_field("dynamic")
    assert _is_machine_field("A")
    assert not _is_machine_field("What is the most likely diagnosis?")
    assert not _is_machine_field("A clinically useful explanation of the answer.")


def test_scripted_template_keeps_visible_text_and_drops_internal_values():
    model = {
        "type": 0,
        "flds": [
            {"name": "Question"},
            {"name": "OptionA"},
            {"name": "CorrectLetter"},
            {"name": "Payload"},
            {"name": "Explanation"},
            {"name": "ConceptId"},
        ],
        "tmpls": [{
            "qfmt": "{{Question}}{{OptionA}}{{CorrectLetter}}{{Payload}}",
            "afmt": "{{FrontSide}}{{Explanation}}{{ConceptId}}",
        }],
    }

    front, back = _selected_fields(
        [
            "Question text",
            "A visible option",
            "A",
            "W3sib3JpZ2luYWxfbGFiZWwiOiJBbnN3ZXIifV0=",
            "Why the answer is correct",
            "concept::c6d7c4072004837a56b5",
        ],
        model,
        0,
    )

    assert front == ["Question text", "A visible option"]
    assert back == ["Why the answer is correct"]


def test_scripted_template_excludes_human_readable_course_metadata():
    model = {
        "type": 0,
        "flds": [
            {"name": "DeckPath"},
            {"name": "Question"},
            {"name": "Option A"},
            {"name": "Explanation"},
            {"name": "CourseTitle"},
            {"name": "SourceLabel"},
        ],
        "tmpls": [{
            "qfmt": "{{DeckPath}}{{Question}}{{Option A}}",
            "afmt": "{{FrontSide}}{{Explanation}}{{CourseTitle}}{{SourceLabel}}",
        }],
    }

    front, back = _selected_fields(
        [
            "Medical School Year Two",
            "Which organism is most likely?",
            "Candida albicans",
            "The clinical findings support Candida.",
            "Microbe Host Interaction",
            "Past paper collection",
        ],
        model,
        0,
    )

    assert front == ["Which organism is most likely?", "Candida albicans"]
    assert back == ["The clinical findings support Candida."]


def test_ucsc_mcq_format_builds_labeled_choices_and_answer():
    names = [
        "Stem", "OptionA", "OptionB", "OptionC", "OptionD", "OptionE", "OptionF",
        "OptionG", "CorrectOptionLabels", "CorrectAnswerHuman", "Explanation",
        "OptionsHuman", "OptionsB64", "NoteGuid", "ShuffleMode", "MetaB64",
    ]
    model = {
        "name": "UCSC MCQ",
        "type": 0,
        "flds": [{"name": name} for name in names],
        "tmpls": [{"qfmt": "{{Stem}}{{OptionsB64}}", "afmt": "{{MetaB64}}"}],
    }
    fields = [
        "What activates trypsinogen?", "Trypsin", "Chymotrypsin",
        "Enterokinase", "Gastrin", "Pepsin", "", "", "C", "Enterokinase",
        "It activates trypsinogen in the duodenum.", "ignored", "encoded options",
        "concept::internal", "dynamic", "huge encoded metadata",
    ]

    front, back = _selected_fields(fields, model, 0)

    assert front == [
        "What activates trypsinogen?", "A. Trypsin", "B. Chymotrypsin",
        "C. Enterokinase", "D. Gastrin", "E. Pepsin",
    ]
    assert back == [
        "Correct answer (C): Enterokinase",
        "Explanation: It activates trypsinogen in the duodenum.",
    ]


def test_formula_delimiters_survive_import_for_client_rendering():
    assert field_to_html(r"Calcium is \(\mathrm{Ca^{2+}}\).") == r"Calcium is \(\mathrm{Ca^{2+}}\)."
