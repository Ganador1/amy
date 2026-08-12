from pathlib import Path
rows = Path('payload/data/observations.csv').read_text().splitlines()[1:]
print(len(rows))
