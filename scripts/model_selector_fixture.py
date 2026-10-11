#!/usr/bin/env python3
"""Manual E10 keyboard/error acceptance, explicitly synthetic and offline.

Requires an explicit fresh/private MRH root. Existing non-fixture bindings are
refused; subsequent runs preserve the fixture's current policy. No credentials,
host subprocess/catalog, service or real model is used.
"""
import argparse
from pathlib import Path
import sys
import time

from mrh import cli, settings
from mrh.bindings import Registry
from mrh.catalog import Catalog, CatalogError, Model, executable_hash


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path)
    p.add_argument('--scenario',required=True,choices=('retired','unavailable','offline','recovery','partial'))
    p.add_argument('--width',type=int,default=120);p.add_argument('--tier',default='light',choices=('light','small','mid','top'))
    args=p.parse_args();registry=Registry(args.root)
    exe=str(Path('/usr/bin/true').resolve())
    candidate={'tool':'codex','label':'SYNTHETIC E10 fixture','executable':exe,
               'executable_sha256':executable_hash(exe),'version':'synthetic-E10-fixture','supported':True}
    rows=(Model('fixture-light-id','Fixture Light',('low','high')),
          Model('fixture-top-id','Fixture Top',('high',)))
    def snapshot(b, models=rows, complete=True):
        return Catalog(b['id'],'codex',b['executable_sha256'],b['version'],
                       'synthetic:E10:'+args.scenario,time.time(),tuple(models),assurance='synthetic',complete=complete)
    bindings=registry.read()['bindings']
    if not bindings:
        b=registry.associate(candidate,expected_revision=0)
        state=settings.read(b['settings_path']);policy=state['policy']
        policy['tiers']['Light']={'model':'fixture-old-id','effort':'high'}
        settings.update(b['settings_path'],expected_revision=state['revision'],policy=policy)
        registry.record_refresh(b,snapshot(b,(Model('fixture-old-id','Old fixture model',('high',)),*rows)))
    elif len(bindings)==1 and bindings[0]['version']=='synthetic-E10-fixture' and bindings[0]['label']=='SYNTHETIC E10 fixture':
        b=bindings[0];registry.verify_profile(b)
    else:raise SystemExit('Refusing non-fixture or multiple bindings; use a fresh private fixture root.')
    class Provider:
        calls=0
        def refresh(self,binding):
            self.calls+=1
            if args.scenario=='offline' or (args.scenario=='recovery' and self.calls==1):
                raise CatalogError('synthetic_refresh_failed')
            if args.scenario=='partial' and self.calls==1:return snapshot(binding,complete=False)
            if args.scenario=='retired':
                return snapshot(binding,(Model('fixture-old-id','Old fixture model',('high',),'retired','synthetic:retirement-notice'),*rows))
            if args.scenario=='unavailable':
                return snapshot(binding,(Model('fixture-old-id','Old fixture model',('high',),'unavailable'),*rows))
            return snapshot(binding)
    print('SYNTHETIC acceptance fixture. No actual outage/retirement/account is asserted.')
    print('Owned settings readback: '+b['settings_path'])
    return cli.main(['model',args.tier,'--root',str(args.root),'--width',str(args.width),'--color'],
                    model_dependencies={'provider':Provider()})


if __name__=='__main__':raise SystemExit(main())
