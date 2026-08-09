#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
"""Add a Comic quality profile with CBZ and CBR custom formats to Readarr.

Run with Readarr stopped:
    python3 scripts/readarr-add-comic-profile.py
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

DB = Path(
    os.environ.get(
        "READARR_DB", Path(__file__).parent.parent / "configs/readarr/config/readarr.db"
    )
)

QUALITY_ITEMS = json.dumps(
    [
        {
            "quality": 0,
            "items": [],
            "allowed": True,
        },  # Unknown Text (CBZ/CBR land here)
        {"quality": 13, "items": [], "allowed": False},  # Unknown Audio
        {"quality": 10, "items": [], "allowed": False},  # MP3
        {"quality": 12, "items": [], "allowed": False},  # M4B
        {"quality": 11, "items": [], "allowed": False},  # FLAC
        {"quality": 1, "items": [], "allowed": True},  # PDF
        {"quality": 4, "items": [], "allowed": False},  # AZW3
        {"quality": 2, "items": [], "allowed": False},  # MOBI
        {"quality": 3, "items": [], "allowed": False},  # EPUB
    ]
)

CUSTOM_FORMATS = [
    {
        "name": "CBZ",
        "specs": json.dumps(
            [
                {
                    "name": "CBZ extension",
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": [{"name": "value", "value": r"(?i)\.cbz"}],
                }
            ]
        ),
    },
    {
        "name": "CBR",
        "specs": json.dumps(
            [
                {
                    "name": "CBR extension",
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": [{"name": "value", "value": r"(?i)\.cbr"}],
                }
            ]
        ),
    },
]

COMICS_ROOT = "/data/media/comics/"


def main():
    if not DB.exists():
        sys.exit(f"Database not found: {DB}")

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Guard: skip if Comic profile already exists
    existing = cur.execute(
        "SELECT Id FROM QualityProfiles WHERE Name = 'Comic'"
    ).fetchone()
    if existing:
        print(f"Comic quality profile already exists (id={existing[0]}), skipping.")
        con.close()
        return

    # 1. Insert Comic quality profile
    cur.execute(
        """
        INSERT INTO QualityProfiles
            (Name, Cutoff, Items, UpgradeAllowed, FormatItems, MinFormatScore, CutoffFormatScore)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("Comic", 0, QUALITY_ITEMS, 1, "[]", 0, 0),
    )
    profile_id = cur.lastrowid
    print(f"Inserted quality profile 'Comic' (id={profile_id})")

    # 2. Insert CBZ and CBR custom formats (skip if already present)
    for cf in CUSTOM_FORMATS:
        row = cur.execute(
            "SELECT Id FROM CustomFormats WHERE Name = ?", (cf["name"],)
        ).fetchone()
        if row:
            print(
                f"Custom format '{cf['name']}' already exists (id={row[0]}), skipping."
            )
            continue
        cur.execute(
            """
            INSERT INTO CustomFormats (Name, Specifications, IncludeCustomFormatWhenRenaming)
            VALUES (?, ?, ?)
            """,
            (cf["name"], cf["specs"], 0),
        )
        print(f"Inserted custom format '{cf['name']}' (id={cur.lastrowid})")

    # 3. Point comics root folder at the new profile
    updated = cur.execute(
        "UPDATE RootFolders SET DefaultQualityProfileId = ? WHERE Path = ?",
        (profile_id, COMICS_ROOT),
    ).rowcount
    if updated:
        print(f"Updated comics root folder to use profile id={profile_id}")
    else:
        print(f"Warning: root folder '{COMICS_ROOT}' not found, skipping update.")

    con.commit()
    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
