from cataloger import parse_args

def test_parse_args_defaults():
    args = parse_args([])
    assert args.max_days is None
    assert args.max_videos is None
    assert args.from_checkpoint is None
    assert args.no_mermaid_thumbnails is False

def test_parse_args_with_options():
    args = parse_args(["--max-days", "7", "--max-videos", "50", "--no-mermaid-thumbnails"])
    assert args.max_days == 7
    assert args.max_videos == 50
    assert args.no_mermaid_thumbnails is True

def test_parse_args_checkpoint():
    args = parse_args(["--from-checkpoint", "/path/to/data.json"])
    assert args.from_checkpoint == "/path/to/data.json"
