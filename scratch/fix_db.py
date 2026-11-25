with open("core/database.py", "r", encoding="utf-8") as f:
    text = f.read()

marker = "    # =========================================================================\n    # STAGE 7: WATERMARK DETECTION & REVIEW SYSTEM"
parts = text.split(marker)

# parts[0] is the original file up to the first occurrence
# parts[1..7] are the segments between duplicate insertions
# parts[8] is the end after the 8th insertion

# Let's see: in each part 1..7, the inserted block ends right before the next method code.
# The inserted block starts at marker and ends with `return [dict(row) for row in cursor.fetchall()]\n\n`
# Actually, the inserted block was:
# marker + ... + 'return [dict(row) for row in cursor.fetchall()]'
# Let's inspect the exact block.

# Rather than guessing, let's take parts[0] and append the clean Stage 7 block to the very end!
# What was parts[1..7]? They contain the original code that followed each 'return [dict(row) for row in cursor.fetchall()]' plus the inserted block!

EOF_MARKER = "# Global database instance\ndb = DatabaseManager()\n"

# Notice that each insertion was:
# Target: "            return [dict(row) for row in cursor.fetchall()]"
# Replacement: "            return [dict(row) for row in cursor.fetchall()]\n\n" + STAGE_7_METHODS
