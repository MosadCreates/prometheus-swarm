"""
Dataset preparation for Prometheus Swarm benchmark (all 50 problems).

Fixes the text/image dataset infrastructure issues described in the paper:
- Text problems: corrects column names to match problem target_column definitions
- Image problems: converts torchvision datasets to image files + CSV format
- Synthetic fallbacks: generates viable alternatives for non-downloadable datasets

Usage:
    python research/prepare_datasets.py              # prepare all
    python research/prepare_datasets.py --problems TX  # text only
    python research/prepare_datasets.py --problems IC  # image only
    python research/prepare_datasets.py --verify       # verify all CSVs
"""

import argparse
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("prepare_datasets")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"

TEXT_FIXES = {
    "TX01": {
        "rename": {"label": "sentiment"},
        "drop": [],
        "desc": "IMDB Reviews: rename label->sentiment for binary sentiment",
    },
    "TX02": {
        "rename": {"label": "category"},
        "drop": [],
        "desc": "AG News: rename label->category for news category",
    },
    "TX03": {
        "transform": "simplify_hate_speech",
        "desc": "Hate Speech: simplify to tweet+label columns",
    },
    "TX04": {
        "reorder": ["label", "text"],
        "desc": "SMS Spam: columns already correct, verify order",
    },
    "TX05": {
        "rename": {"label": "rating"},
        "drop": ["title"],
        "desc": "Amazon Reviews: rename label->rating, drop title",
    },
    "TX06": {
        "transform": "generate_toxic_comments",
        "desc": "Jigsaw Toxic: generate synthetic toxic/clean comments",
    },
    "TX07": {
        "desc": "Email Classification: already correct (text,category)",
    },
    "TX08": {
        "transform": "simplify_paper_abstracts",
        "desc": "Paper Abstracts: keep abstract+subdomain, drop title",
    },
    "TX09": {
        "rename": {"text_": "text", "label": "label"},
        "drop": ["category", "rating"],
        "desc": "Fake Reviews: rename text_->text, drop category+rating",
    },
    "TX10": {
        "rename": {"labels": "language"},
        "desc": "Language Detection: rename labels->language",
    },
}

IMAGE_PROBLEMS = [
    {
        "id": "IC01",
        "dataset": "FashionMNIST",
        "csv_name": "ic01_fashion_mnist.csv",
        "torchvision_name": "FashionMNIST",
        "target_col": "label",
        "num_classes": 10,
        "desc": "Fashion MNIST from torchvision",
    },
    {
        "id": "IC02",
        "dataset": "MNIST",
        "csv_name": "ic02_mnist.csv",
        "torchvision_name": "MNIST",
        "target_col": "digit",
        "num_classes": 10,
        "desc": "MNIST digits from torchvision",
    },
    {
        "id": "IC03",
        "dataset": "CIFAR10",
        "csv_name": "ic03_cifar10.csv",
        "torchvision_name": "CIFAR10",
        "target_col": "label",
        "num_classes": 10,
        "desc": "CIFAR-10 from torchvision",
    },
    {
        "id": "IC04",
        "dataset": "BrainMRI",
        "csv_name": "ic04_image_dataset.csv",
        "target_col": "has_tumor",
        "num_classes": 2,
        "synthetic": True,
        "desc": "Brain MRI: synthetic tumor/no-tumor images",
    },
    {
        "id": "IC05",
        "dataset": "ChestXRay",
        "csv_name": "ic05_chest_xray.csv",
        "target_col": "label",
        "num_classes": 2,
        "synthetic": True,
        "desc": "Chest X-Ray: synthetic normal/pneumonia images",
    },
    {
        "id": "IC06",
        "dataset": "GTSRB",
        "csv_name": "ic06_gtsrb.csv",
        "torchvision_name": "GTSRB",
        "target_col": "sign",
        "num_classes": 43,
        "desc": "German Traffic Signs from torchvision",
    },
    {
        "id": "IC07",
        "dataset": "Flowers",
        "csv_name": "ic07_flowers.csv",
        "torchvision_name": "Flowers102",
        "target_col": "species",
        "num_classes": 102,
        "desc": "Flowers102 from torchvision",
    },
    {
        "id": "IC08",
        "dataset": "DiabeticRetinopathy",
        "csv_name": "ic08_diabetic_retinopathy.csv",
        "target_col": "has_disease",
        "num_classes": 2,
        "synthetic": True,
        "desc": "Diabetic Retinopathy: synthetic disease/no-disease images",
    },
]


# ── helpers ──────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_csv(filepath: Path):
    import pandas as pd

    return pd.read_csv(filepath)


def _save_csv(df, filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(filepath, index=False, encoding="utf-8")
    logger.info(f"  wrote {len(df)} rows -> {filepath}")


# ── text fixes ───────────────────────────────────────────────────────


# (replaced by fix_text_dataset below)


def fix_text_dataset(pid: str):
    """Apply the correct fix for a text problem."""
    fix = TEXT_FIXES.get(pid)
    if not fix:
        return

    # Find the CSV path
    name_map = {
        "TX01": "tx01_imdb_reviews.csv",
        "TX02": "tx02_ag_news.csv",
        "TX03": "tx03_hate_speech.csv",
        "TX04": "tx04_sms_spam.csv",
        "TX05": "tx05_amazon_reviews.csv",
        "TX06": "tx06_jigsaw_toxic.csv",
        "TX07": "tx07_email_classification.csv",
        "TX08": "tx08_paper_abstracts.csv",
        "TX09": "tx09_fake_reviews.csv",
        "TX10": "tx10_language_detection.csv",
    }

    path = DATA_DIR / name_map[pid]
    if not path.exists():
        logger.warning(f"  {pid}: file not found at {path}")
        return

    logger.info(f"  {pid}: {fix.get('desc', '')}")

    transform = fix.get("transform")
    if transform == "simplify_hate_speech":
        _transform_tx03(path)
    elif transform == "generate_toxic_comments":
        _transform_tx06(path)
    elif transform == "simplify_paper_abstracts":
        _transform_tx08(path)
    else:
        df = _load_csv(path)
        if fix.get("rename"):
            df = df.rename(columns=fix["rename"])
        if fix.get("drop"):
            df = df.drop(columns=[c for c in fix["drop"] if c in df.columns], errors="ignore")
        if fix.get("reorder"):
            cols = [c for c in fix["reorder"] if c in df.columns]
            cols += [c for c in df.columns if c not in fix["reorder"]]
            df = df[cols]
        _save_csv(df, path)


def _transform_tx03(path: Path):
    """Simplify hate speech CSV: keep only tweet + label."""
    import pandas as pd

    df = pd.read_csv(str(path))
    if "tweet" in df.columns and "class" in df.columns:
        df = df[["tweet", "class"]].rename(columns={"class": "label"})
    elif "tweet" in df.columns and "label" in df.columns:
        df = df[["tweet", "label"]]
    else:
        logger.warning(f"  TX03: unexpected columns {df.columns.tolist()}")
        return
    _save_csv(df, path)


def _transform_tx06(path: Path):
    """Generate synthetic toxic/clean comments for Jigsaw Toxic.

    The original file lacks a text column. We generate realistic comment-like
    text with binary toxic labels (0 = clean, 1 = toxic).
    """
    import pandas as pd
    import numpy as np

    CLEAN_TEMPLATES = [
        "I completely agree with your point about {topic}. Well said!",
        "Great discussion thread, everyone. Really insightful comments.",
        "Thanks for sharing your perspective on {topic}. I learned something new.",
        "This is a well-reasoned argument. Let me add that {topic}.",
        "Interesting take. I hadn't considered {topic} from that angle.",
        "Appreciate the thoughtful analysis. Looking forward to part 2.",
        "Can someone clarify what {topic} means in this context?",
        "Solid write-up. Bookmarking this for later reference.",
        "This changed my mind about {topic}. Thanks for the perspective.",
        "Good resource. Sharing this with my team at work.",
    ]
    TOXIC_TEMPLATES = [
        "You're an idiot if you believe {topic}. Complete moron.",
        "Shut up and go back to {place}. Nobody wants you here.",
        "This is the dumbest thing I've ever read. You're clueless.",
        "Go die in a fire. People like you are the worst.",
        "Stupid piece of trash. Delete your account immediately.",
        "You have no idea what you're talking about. Pathetic.",
        "Get lost moron. Go bother someone else with your garbage.",
        "This post is garbage and you should feel bad for posting it.",
        "Are you seriously this stupid? Unbelievable.",
        "Worthless post from a worthless person. Blocked and reported.",
    ]
    TOPICS = [
        "the new policy changes",
        "AI regulation",
        "climate data",
        "the latest update",
        "this proposal",
        "the study results",
        "economic trends",
        "health guidelines",
        "tech innovation",
        "education reform",
        "the budget plan",
        "market analysis",
    ]
    PLACES = ["your mom's basement", "4chan", "wherever you came from", "Reddit"]

    rng = np.random.default_rng(42)
    n = min(
        5000,
        (
            max(500, int(path.stat().st_size / 200))
            if path.exists() and path.stat().st_size > 100
            else 5000
        ),
    )

    texts, toxics = [], []
    for _ in range(n):
        is_toxic = bool(rng.integers(0, 2))
        template = rng.choice(TOXIC_TEMPLATES if is_toxic else CLEAN_TEMPLATES)
        topic = rng.choice(TOPICS)
        text = template.format(topic=topic, place=rng.choice(PLACES))
        texts.append(text)
        toxics.append(1 if is_toxic else 0)

    df = pd.DataFrame({"text": texts, "toxic": toxics})
    _save_csv(df, path)


def _transform_tx08(path: Path):
    """Simplify Paper Abstracts: drop title col, keep abstract+subdomain."""
    import pandas as pd

    df = pd.read_csv(str(path))
    keep_cols = [c for c in ["abstract", "subdomain"] if c in df.columns]
    if keep_cols and len(keep_cols) == 2:
        df = df[keep_cols]
        _load_and_relabel(df, path)
    else:
        # Try alternative column names
        text_cols = [c for c in df.columns if df[c].dtype == "object" and c != "subdomain"]
        if text_cols and "subdomain" in df.columns:
            df = df[[text_cols[0], "subdomain"]]
            _save_csv(df, path)


def _load_and_relabel(df, path):
    _save_csv(df, path)


# ── image generation ─────────────────────────────────────────────────


def generate_image_dataset(pid: str, info: dict):
    """Generate a proper image dataset with image files + CSV."""
    import numpy as np

    target_col = info["target_col"]
    csv_name = info.get("csv_name", f"{pid.lower()}_{info['dataset'].lower()}.csv")
    csv_path = DATA_DIR / csv_name
    img_dir = _ensure_dir(IMAGES_DIR / pid)

    if info.get("synthetic"):
        _generate_synthetic_images(pid, img_dir, csv_path, info)
        return

    # torchvision dataset
    tv_name = info.get("torchvision_name")
    if not tv_name:
        logger.warning(f"  {pid}: no torchvision_name, skipping")
        return

    _generate_from_torchvision(pid, img_dir, csv_path, tv_name, info)


def _generate_synthetic_images(pid: str, img_dir: Path, csv_path: Path, info: dict):
    """Generate synthetic RGB images with known labels."""
    import pandas as pd
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(42)
    n_per_class = 250
    n_total = n_per_class * info["num_classes"]
    target_col = info["target_col"]

    _ensure_dir(img_dir)
    rows = []
    label_names = {
        "has_tumor": {0: "no_tumor", 1: "has_tumor"},
        "label": {0: "class_0", 1: "class_1"},
        "has_disease": {0: "no_disease", 1: "has_disease"},
        "sign": {i: str(i) for i in range(info["num_classes"])},
        "species": {i: f"species_{i}" for i in range(info["num_classes"])},
    }
    label_map = label_names.get(target_col, {i: str(i) for i in range(info["num_classes"])})

    for cls in range(info["num_classes"]):
        for i in range(n_per_class):
            img = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
            # Add class-specific pattern for differentiation
            img[cls * 5 : (cls * 5 + 10), :, 0] = 255
            fname = f"class_{cls}_{i:04d}.png"
            fpath = img_dir / fname
            Image.fromarray(img).save(str(fpath))
            rows.append({"image_path": str(fpath.resolve()), target_col: label_map.get(cls, cls)})

    df = pd.DataFrame(rows)
    _save_csv(df, csv_path)
    logger.info(f"  {pid}: {n_total} synthetic images -> {img_dir}")


def _generate_from_torchvision(pid: str, img_dir: Path, csv_path: Path, tv_name: str, info: dict):
    """Download a torchvision dataset, save images to disk, create CSV."""
    import pandas as pd
    import torch
    import torchvision.transforms as T
    from PIL import Image

    if tv_name == "GTSRB":
        try:
            from torchvision.datasets import GTSRB as TVDataset
        except ImportError:
            logger.warning(f"  {pid}: GTSRB not available in torchvision, using synthetic")
            _generate_synthetic_images(
                pid, img_dir, csv_path, {**info, "synthetic": True, "num_classes": 43}
            )
            return
    elif tv_name == "Flowers102":
        try:
            from torchvision.datasets import Flowers102 as TVDataset
        except ImportError:
            logger.warning(f"  {pid}: Flowers102 not available in torchvision, using synthetic")
            _generate_synthetic_images(
                pid, img_dir, csv_path, {**info, "synthetic": True, "num_classes": 102}
            )
            return
    else:
        tv_module = __import__("torchvision.datasets", fromlist=[tv_name])
        TVDataset = getattr(tv_module, tv_name, None)
        if TVDataset is None:
            logger.warning(f"  {pid}: {tv_name} not found in torchvision, using synthetic")
            _generate_synthetic_images(pid, img_dir, csv_path, {**info, "synthetic": True})
            return

    _ensure_dir(img_dir)
    target_col = info["target_col"]

    try:
        if tv_name == "GTSRB":
            train_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                split="train",
                download=True,
                transform=T.ToTensor(),
            )
            # GTSRB doesn't have a standard test split in torchvision
            all_data = list(train_data)
        elif tv_name == "Flowers102":
            train_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                split="train",
                download=True,
                transform=T.ToTensor(),
            )
            test_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                split="test",
                download=True,
                transform=T.ToTensor(),
            )
            val_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                split="val",
                download=True,
                transform=T.ToTensor(),
            )
            all_data = list(train_data) + list(test_data) + list(val_data)
        else:
            train_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                train=True,
                download=True,
                transform=T.ToTensor(),
            )
            test_data = TVDataset(
                root=str(DATA_DIR / "torchvision_data"),
                train=False,
                download=True,
                transform=T.ToTensor(),
            )
            all_data = list(train_data) + list(test_data)
    except Exception as e:
        logger.warning(f"  {pid}: torchvision download failed ({e}), using synthetic")
        _generate_synthetic_images(pid, img_dir, csv_path, {**info, "synthetic": True})
        return

    rows = []
    # Cap at 10000 samples max for speed
    max_samples = min(len(all_data), 10000)
    all_data = all_data[:max_samples]

    for idx, (img_tensor, label) in enumerate(all_data):
        img_pil = T.ToPILImage()(img_tensor)
        if img_pil.mode != "RGB":
            img_pil = img_pil.convert("RGB")
        fname = f"img_{idx:06d}.png"
        fpath = img_dir / fname
        img_pil.save(str(fpath))
        label_val = label if isinstance(label, (int, str)) else int(label)
        rows.append({"image_path": str(fpath.resolve()), target_col: label_val})

    df = pd.DataFrame(rows)
    _save_csv(df, csv_path)
    logger.info(f"  {pid}: {len(rows)} images from {tv_name} -> {img_dir}")


# ── verification ─────────────────────────────────────────────────────


def verify_all():
    """Verify all 50 problem CSVs are loadable and have expected columns."""
    import pandas as pd
    from research.run_benchmark import load_problems

    problems = load_problems()
    issues = []
    ok = 0

    for p in problems:
        pid = p["id"]
        path = p["dataset"]["path"]
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = PROJECT_ROOT / path

        if not full_path.exists():
            issues.append(f"  {pid}: MISSING at {full_path}")
            continue

        try:
            df = pd.read_csv(str(full_path))
        except Exception as e:
            issues.append(f"  {pid}: UNREADABLE - {e}")
            continue

        target = p.get("target_column")
        if target and target not in df.columns:
            # For image CSVs, check if image_path exists
            modality = p.get("modality", "")
            if modality == "image":
                has_path = any(k in str(df.columns) for k in ["path", "file", "image"])
                if not has_path:
                    issues.append(f"  {pid}: no image path column in {df.columns.tolist()}")
                    continue
            else:
                issues.append(f"  {pid}: target '{target}' not in columns {df.columns.tolist()}")
                continue

        if pid.startswith("TX"):
            # Verify text CSV has at least one text column
            text_cols = [c for c in df.columns if df[c].dtype == "object" and c != target]
            if not text_cols:
                issues.append(f"  {pid}: no text column found")
                continue

        ok += 1

    logger.info(f"\nVerification: {ok}/50 CSVs OK")
    if issues:
        logger.warning(f"Issues ({len(issues)}):")
        for issue in issues:
            logger.warning(issue)

    return len(issues) == 0


# ── main ─────────────────────────────────────────────────────────────


def prepare_all(problems_filter: str = "all"):
    """Prepare all datasets for the benchmark."""
    import numpy as np

    logger.info("=" * 60)
    logger.info("Prometheus Swarm — Dataset Preparation")
    logger.info("=" * 60)

    if problems_filter in ("all", "TX", "text"):
        logger.info("\n─ Fixing text datasets ─")
        for pid in ["TX01", "TX02", "TX03", "TX04", "TX05", "TX06", "TX07", "TX08", "TX09", "TX10"]:
            try:
                fix_text_dataset(pid)
            except Exception as e:
                logger.error(f"  {pid}: FAILED - {e}")

    if problems_filter in ("all", "IC", "image"):
        logger.info("\n─ Preparing image datasets ─")
        for info in IMAGE_PROBLEMS:
            pid = info["id"]
            try:
                logger.info(f"  {pid}: {info['desc']}")
                generate_image_dataset(pid, info)
            except Exception as e:
                logger.error(f"  {pid}: FAILED - {e}", exc_info=True)

    if problems_filter == "all":
        logger.info("\n─ Verifying all datasets ─")
        verify_all()

    logger.info("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare benchmark datasets")
    parser.add_argument(
        "--problems",
        choices=["all", "TX", "IC", "text", "image"],
        default="all",
        help="Which problem types to prepare",
    )
    parser.add_argument("--verify", action="store_true", help="Verify all CSVs only")
    args = parser.parse_args()

    if args.verify:
        verify_all()
    else:
        prepare_all(args.problems)
