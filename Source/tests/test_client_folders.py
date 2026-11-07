"""Client download folders are named after the game, not its internal id, and stay put once chosen."""
import json

from lantool.game_directory import assign_client_folders, safe_folder_name


def assign(tmp_path, games):
    return assign_client_folders(tmp_path / "games", tmp_path / "state.json", games)


def test_folder_uses_display_name_without_the_id_suffix(tmp_path):
    result = assign(tmp_path, [("battlefield-bad-company-2-3fa91c", "Battlefield Bad Company 2")])
    assert result["battlefield-bad-company-2-3fa91c"] == tmp_path / "games" / "Battlefield Bad Company 2"


def test_safe_folder_name_cleans_windows_hazards():
    assert safe_folder_name('Half-Life 2: Episode "One"?') == "Half-Life 2 Episode One"
    assert safe_folder_name("Game. ") == "Game"
    assert safe_folder_name("CON") == "CON game"
    assert safe_folder_name("aux.txt") == "aux.txt game"
    assert safe_folder_name("..") == "Game"
    assert safe_folder_name("") == "Game"
    assert safe_folder_name("a/b\\c") == "a b c"
    assert len(safe_folder_name("x" * 200)) <= 48


def test_existing_download_under_the_old_id_folder_keeps_being_used(tmp_path):
    (tmp_path / "games" / "cod4-aaaaaa").mkdir(parents=True)
    result = assign(tmp_path, [("cod4-aaaaaa", "Call of Duty 4")])
    assert result["cod4-aaaaaa"] == tmp_path / "games" / "cod4-aaaaaa"


def test_two_games_with_one_name_get_a_suffix_only_for_the_second(tmp_path):
    result = assign(tmp_path, [("map-pack-bbbbbb", "Map Pack"), ("map-pack-aaaaaa", "map pack")])
    assert result["map-pack-aaaaaa"] == tmp_path / "games" / "map pack"
    assert result["map-pack-bbbbbb"] == tmp_path / "games" / "map pack (2)"


def test_unrelated_non_empty_folder_is_never_adopted(tmp_path):
    other = tmp_path / "games" / "Quake"
    other.mkdir(parents=True)
    (other / "pak0.pak").write_bytes(b"x")
    result = assign(tmp_path, [("quake-111111", "Quake")])
    assert result["quake-111111"] == tmp_path / "games" / "Quake (2)"


def test_empty_existing_folder_is_fine_to_use(tmp_path):
    (tmp_path / "games" / "Quake").mkdir(parents=True)
    assert assign(tmp_path, [("quake-111111", "Quake")])["quake-111111"] == tmp_path / "games" / "Quake"


def test_choice_is_remembered_even_after_files_arrive_and_the_name_changes(tmp_path):
    first = assign(tmp_path, [("quake-111111", "Quake")])["quake-111111"]
    first.mkdir(parents=True)
    (first / "pak0.pak").write_bytes(b"x")  # now non-empty, as after a partial download
    again = assign(tmp_path, [("quake-111111", "Quake")])["quake-111111"]
    renamed = assign(tmp_path, [("quake-111111", "Quake Remastered")])["quake-111111"]
    assert again == renamed == first


def test_second_game_does_not_take_a_remembered_name_before_its_folder_exists(tmp_path):
    assign(tmp_path, [("a-aaaaaa", "Same")])
    result = assign(tmp_path, [("a-aaaaaa", "Same"), ("b-bbbbbb", "Same")])
    assert result["a-aaaaaa"].name == "Same"
    assert result["b-bbbbbb"].name == "Same (2)"


def test_bad_or_hostile_saved_state_is_ignored(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"g-111111": "..\\evil", "h-222222": "ok name"}), encoding="utf-8")
    result = assign(tmp_path, [("g-111111", "Good Game"), ("h-222222", "Whatever")])
    assert result["g-111111"] == tmp_path / "games" / "Good Game"
    assert result["h-222222"] == tmp_path / "games" / "ok name"
    (tmp_path / "state.json").write_text("not json", encoding="utf-8")
    assert assign(tmp_path, [("g-111111", "Good Game")])["g-111111"].name == "Good Game"


def test_unwritable_state_file_still_returns_folders(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, so its children cannot be created")
    result = assign_client_folders(tmp_path / "games", blocker / "state.json", [("g-111111", "Good Game")])
    assert result["g-111111"] == tmp_path / "games" / "Good Game"
