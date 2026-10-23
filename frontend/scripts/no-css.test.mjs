import { test } from 'node:test';
import assert from 'node:assert/strict';
import { inspect } from './no-css.mjs';
test('rejects styles and replacement controls', () => {
  for (const source of ['<div style={{color:"red"}} />', '<button />', 'import "./a.css"', 'makeStyles({root:{color:"red"}})', '<div className="x" />', '<svg />', 'import x from "antd"', '<div {...props} />']) {
    assert.ok(inspect('sample.tsx', source).length, source);
  }
  assert.ok(inspect('sample.scss', '').length);
  assert.equal(inspect('sample.tsx', 'import { Button } from "@fluentui/react-components"; const x = <Button appearance="primary">OK</Button>;').length, 0);
});
test('rejects alternate injection paths', () => {
  for (const source of [
    'import("./a.sass")', 'require("styled-components")', 'import(path)',
    'element.style.color = "red"', 'sheet.insertRule("body {}")',
    '<div dangerouslySetInnerHTML={{__html: html}} />', '<progress />', '<td />',
    'React.createElement("button")', 'document.createElement("style")',
    'element.setAttribute("style", "color:red")', 'element["style"].color = "red"',
  ]) assert.ok(inspect('sample.tsx', source).length, source);
  for (const source of ['<link rel="stylesheet" href="x.css">', '<style>body {}</style>', '<input>']) {
    assert.ok(inspect('index.html', source).length, source);
  }
  for (const extension of ['css', 'scss', 'sass', 'less', 'styl']) assert.ok(inspect(`a.${extension}`, '').length);
  assert.equal(inspect('sample.tsx', 'import("./dashboard"); const x = <section><p>OK</p></section>;').length, 0);
});
test('allows token layout only on semantic containers', () => {
  assert.deepEqual(inspect('layout.tsx', 'import {makeStyles,tokens} from "@fluentui/react-components"; const useStyles=makeStyles({root:{display:"grid",gap:tokens.spacingHorizontalM,"@media (max-width: 760px)":{gridTemplateColumns:"1fr"}}}); const x=<main className={styles.root} />;'), []);
  for (const source of ['makeStyles({root:{"& .fui-Button":{display:"grid"}}})', 'makeStyles({root:{padding:"12px"}})', '<Button className={styles.root} />', 'makeStyles({root:{borderRadius:"8px"}})']) assert.ok(inspect('bad.tsx', source).length, source);
});