"""Current configuration presentation, not runtime/model support evidence."""
import copy
import re
import unittest
from mrh.settings_schema import default_settings
from mrh.terminal import cell_width, render_configuration, render_stats, sanitize_text


def current():
    value=default_settings()
    value['policy'].update(top_mode='Fixed',fixed={'model':'fixed-example'},tiers={
        'Light':{'model':'light-example'},'Small':{'model':'small-example','effort':'low'},
        'Mid':{'model':'mid-example','effort':'high'},'Top':{'model':'IGNORED-TOP'}})
    return value


class ConfigurationTableTests(unittest.TestCase):
    def test_wide_aligned_current_table_and_top_emphasis_shared_surfaces(self):
        stats={'partition':'live','tiers':{'Top':99},'confirmed_children':0}
        for renderer in (lambda cfg:render_configuration(cfg,width=120,color=True),
                         lambda cfg:render_stats(stats,width=120,color=True,configuration=cfg)):
            text=renderer(current());plain=[sanitize_text(line) for line in text.splitlines()]
            header=next(line for line in plain if 'REQUESTED MODEL' in line)
            for model,effort,mode in [('light-example','inherit','Model'),('small-example','low','Model'),('fixed-example','inherit','Fixed')]:
                row=next(line for line in plain if model in line)
                self.assertEqual(row.index(model),header.index('REQUESTED MODEL'))
                self.assertEqual(row.index(effort),header.index('EFFORT'))
                self.assertEqual(row.index(mode),header.rindex('MODE'))
            top=next(line for line in text.splitlines() if 'fixed-example' in line)
            self.assertIn('\x1b[38;2;173;178;250m\x1b[1m',top)
            self.assertNotIn('IGNORED-TOP',text)
            table=text.split('REQUESTED MODEL',1)[1].split('Routing requested:',1)[0]
            self.assertNotIn('99',table);self.assertNotIn('TASKS',header);self.assertNotIn('SHARE',header)

    def test_main_has_no_fixed_target_or_invented_effort_and_narrow_unset(self):
        value=current();value['policy']['top_mode']='Main';value['policy']['tiers'].pop('Light')
        for width in (24,28,56,80,120):
            text=render_configuration(value,width=width,color=False)
            self.assertTrue(all(cell_width(line)<=width for line in text.splitlines()))
            self.assertNotIn('fixed-example',text);self.assertNotIn('IGNORED-TOP',text)
            self.assertIn('Unset',text);self.assertIn('Preserve',text);self.assertIn('Main',text)
            if width>=80:
                top=next(line for line in text.splitlines() if 'Current main agent' in line)
                self.assertIn('—',top);self.assertNotIn('inherit',top);self.assertNotIn('high',top)
            else:
                self.assertIn('Effort: —',text)

    def test_long_ids_preserved_and_terminal_controls_sanitized(self):
        value=current();value['policy']['tiers']['Light']['model']='a'*128
        value['policy']['fixed']['model']='\x1b]0;unsafe\x07fixed-example'
        for width in (28,80,120):
            text=render_configuration(value,width=width,color=False)
            self.assertEqual(sum(map(len,re.findall(r'a{2,}',text))),128)
            self.assertNotIn('unsafe',text);self.assertNotIn('\x1b',text)
            self.assertTrue(all(cell_width(line)<=width for line in text.splitlines()))


if __name__=='__main__':unittest.main()
