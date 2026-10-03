"""Experiment call reservations only; does not read or implement memory/skill assets."""
import argparse
import json
import sqlite3
from pathlib import Path


class LearningBudget:
    def __init__(self, path, limit=None):
        self.path=Path(path)
        if limit is None and not self.path.is_file(): raise ValueError('Budget pool must be explicitly initialized')
        self.db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS pool (id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, quota INTEGER NOT NULL, used INTEGER, evidence TEXT);')
        if limit is not None:
            if type(limit) is not int or limit<0: raise ValueError('Invalid pool limit')
            self.db.execute('INSERT OR IGNORE INTO pool VALUES(1,?)',(limit,))
            if self.db.execute('SELECT cap FROM pool').fetchone()[0]!=limit: raise ValueError('Existing pool cap cannot be changed')
        if not self.db.execute('SELECT cap FROM pool').fetchone(): raise ValueError('Missing pool configuration')

    def snapshot(self):
        rows=self.db.execute('SELECT id,quota,used,evidence FROM leases ORDER BY id').fetchall()
        cap=self.db.execute('SELECT cap FROM pool').fetchone()[0]
        charged=sum(quota if used is None else used for _,quota,used,_ in rows)
        return {'cap':cap,'chargedOrReserved':charged,'remaining':cap-charged,'leases':[{'id':id_,'quota':q,'used':u,'evidence':e} for id_,q,u,e in rows]}

    def reserve(self, id_, requested):
        if type(requested) is not int or requested<0: raise ValueError('Invalid quota')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            quota=min(requested,self.snapshot()['remaining'])
            self.db.execute('INSERT INTO leases VALUES(?,?,NULL,NULL)',(id_,quota))
            self.db.execute('COMMIT');return quota
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def settle(self,id_,used,evidence):
        if type(used) is not int or used<0 or not evidence: raise ValueError('Invalid settlement')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT quota,used,evidence FROM leases WHERE id=?',(id_,)).fetchone()
            if row is None or used>row[0]: raise ValueError('Settlement exceeds reserved quota')
            if row[1] is not None and (row[1]!=used or row[2]!=evidence): raise ValueError('Lease already settled differently')
            self.db.execute('UPDATE leases SET used=?,evidence=? WHERE id=?',(used,evidence,id_))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def close(self): self.db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path)
    parser.add_argument('--init',type=int)
    args=parser.parse_args()
    pool=LearningBudget(args.path,args.init)
    try: print(json.dumps(pool.snapshot(),indent=2))
    finally: pool.close()


if __name__=='__main__':main()
