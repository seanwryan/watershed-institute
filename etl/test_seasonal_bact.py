"""Meaningful source preservation checks; synthetic data only."""
from io import BytesIO
import unittest
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from etl.seasonal_bact import inspect_workbook, result_value


def source_bytes():
    w=Workbook();s=w.active;s.title='SURVEY123'
    s.append(['Sample Code','Monitoring Site ID','Date','Water Temperature','E. coli','Notes'])
    s.append(['AC1a_2026-05-17','AC1a','2026-05-17',0,128.1,'Outlier; Flagged <script>'])
    s['D2'].font=Font(color='FFFF0000');s['D2'].fill=PatternFill('solid',fgColor='FFFFFF00');s['D2'].comment=Comment('Keep original zero','Staff')
    s.append(['repeat','AC1a','2026-05-17','3.5?','=1+1',''])
    s['D10']='=A10'
    t=w.create_sheet('IDEXX');t.append(['Sample Code','Sample ID','Date Collected','Color Change',None,'Ttl Coli',None,None,'E. coli','Data Conditions'])
    t.append([None,None,None,'Lg Wells','Sm Wells','MPN',None,None,'MPN'])
    t.append(['AC1a_2026-05-17','AC1a','2026-05-17',1,2,10,None,None,'> 2419.6','Flagged; Incomplete'])
    t.append(['zero','AC2','2026-05-18',None,None,None,None,None,0])
    t['I20']='=1+1'
    o=BytesIO();w.save(o);return o.getvalue()


class SourceTests(unittest.TestCase):
    def test_limits_decimals_uncertainty_and_zero_remain_distinct(self):
        for value,state,number,qual in [(128.1,'numeric','128.1','='),(0,'numeric','0','='),('> 2419.6','censored','2419.6','>'),('< 1.0','censored','1.0','<'),('3.5?','uncertain',None,None),('NaN','unparsed',None,None)]:
            r=result_value(value);self.assertEqual((r['state'],r['number'],r['qualifier']),(state,number,qual))
        self.assertEqual(result_value(None,'=1+1')['state'],'missing_cached_result')
        self.assertEqual(result_value('#REF!','=broken',True)['state'],'formula_error')

    def test_preserves_source_identity_formatting_and_formula_tail(self):
        data=source_bytes();r=inspect_workbook(data,'source.xlsx')
        self.assertEqual(r['row_count'],4)
        self.assertEqual(r['sha256'],inspect_workbook(data,'renamed.xlsx')['sha256'])
        row=r['rows'][0];self.assertEqual(row['site_code'],'AC1a')
        self.assertEqual(row['parameters']['Water Temperature']['number'],'0')
        self.assertEqual(row['parameters']['E. coli']['number'],'128.1')
        self.assertEqual(row['cells']['D2']['font_color']['value'],'FFFF0000')
        self.assertEqual(row['cells']['D2']['comment'],'Keep original zero')
        self.assertIn('Repeated site/date in this sheet; no match selected',row['issues'])
        self.assertEqual(r['rows'][1]['parameters']['E. coli']['formula'],'=1+1')
        self.assertEqual(r['rows'][2]['parameters']['E. coli']['qualifier'],'>')
        self.assertEqual(r['rows'][2]['annotations']['Data Conditions'],'Flagged; Incomplete')
        self.assertTrue(any(not s['present'] for s in r['sheets']))

    def test_rejects_analysis_layout_and_invalid_data(self):
        w=Workbook();w.active.title='Temperature';b=BytesIO();w.save(b)
        with self.assertRaises(ValueError):inspect_workbook(b.getvalue(),'analysis.xlsx')
        with self.assertRaises(ValueError):inspect_workbook(b'bad','bad.xlsx')
