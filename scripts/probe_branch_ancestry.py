"""Does a FRESH branch created from main show other users' commits?

If yes -> normal git ancestry inheritance, NOT an access-control bug.
If no  -> the earlier observation needs another explanation.
"""
import os, time
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import bauplan

c = bauplan.Client()
me = c.info().user
user = os.getenv("BAUPLAN_USERNAME")
b = f"{user}.ancestry-probe-{int(time.time())}"

print(f"authenticated as: {me.username if hasattr(me,'username') else me}")
print(f"creating fresh branch {b} from main\n")
c.create_branch(b, from_ref="main")
try:
    commits = list(c.get_commits(ref=b, limit=15))
    print(f"commits visible on a BRAND-NEW branch: {len(commits)}\n")
    authors = {}
    for cm in commits:
        who = None
        for attr in ("authors","author","committer"):
            v = getattr(cm, attr, None)
            if v:
                who = str(v[0].username if isinstance(v,list) and hasattr(v[0],'username')
                          else getattr(v,'username',v))
                break
        authors[who] = authors.get(who,0)+1
        print(f"  {str(getattr(cm,'ref',''))[:22]:22s} {str(getattr(cm,'committed_date',''))[:10]}  {who}")
    print(f"\ndistinct authors on a branch created seconds ago: {authors}")
    print("\nVERDICT:", "ANCESTRY INHERITANCE (normal git) — not an access-control bug"
          if len(authors) > 1 or (authors and user not in str(authors))
          else "only my own commits — earlier observation needs another explanation")
finally:
    c.delete_branch(b)
    print(f"\ncleaned up {b}")
