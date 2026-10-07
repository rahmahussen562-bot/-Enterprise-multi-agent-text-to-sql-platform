import { describe, it, expect } from 'vitest';
import { compareCells, csv, workbookParts } from './data';
describe('financial export integrity',()=>{
  it('sorts large decimals without Number precision loss',()=>{expect(compareCells('12345678901234567890.000001','12345678901234567890.000002')).toBe(-1);expect(compareCells('-2.1','-2.09')).toBe(-1);expect(compareCells('1.00',1)).toBe(0);});
  it('escapes CSV formula injection while preserving numbers and Unicode',()=>{const output=csv(['name','value'],[['=HYPERLINK("x")',-12],['عميل','+cmd'],['a,b','a"b']]);expect(output).toContain("'=");expect(output).toContain("'+cmd");expect(output).toContain('"-12"');expect(output).toContain('عميل');expect(output).toContain('a""b');expect(output.startsWith('\uFEFF')).toBe(true);});
  it('writes Excel cells as literal strings and preserves decimal precision',()=>{const parts=workbookParts(['amount','identity'],[['12345678901234567890.123456','=HYPERLINK("x")'],['عميل','A&B']]);const sheet=parts['xl/worksheets/sheet1.xml'];expect(sheet).toContain('12345678901234567890.123456');expect(sheet).toContain('t="inlineStr"');expect(sheet).not.toContain('<f>');expect(sheet).toContain('A&amp;B');expect(sheet).toContain('عميل');expect(Object.keys(parts)).toHaveLength(6);});
});
