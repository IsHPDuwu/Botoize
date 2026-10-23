import ts from 'typescript';
import { readdirSync, readFileSync } from 'node:fs';
import { resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

export function inspect(name, source) {
  const errors = [];
  if (/\.(css|scss|sass|less|styl)$/i.test(name)) errors.push('样式文件');
  const banned = /(?:\.(?:css|scss|sass|less|styl)|griffel|styled-components|emotion|tailwind|@mui|antd|chakra|bootstrap)/i;
  function checkModule(id) {
    if (banned.test(id) || (!id.startsWith('.') && !/^(react(?:-dom)?(?:\/.*)?|@fluentui\/react-(components|icons))$/.test(id))) errors.push('非许可依赖或样式导入');
  }
  const ast = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      const module = node.moduleSpecifier;
      if (module && ts.isStringLiteral(module)) {
        checkModule(module.text);
      }
    }
    if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(ast) === 'require')) {
      if (node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0])) checkModule(node.arguments[0].text);
      else errors.push('不可审计的动态依赖');
    }
    if (ts.isCallExpression(node)) {
      const name = node.expression.getText(ast);
      if (/(?:^|\.)(?:createElement|setAttribute)$/.test(name) && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
        if (/^(?:style|class|button|input|select|textarea|table|dialog|svg|canvas)$/.test(node.arguments[0].text)) errors.push('命令式样式或替代控件');
      }
    }
    if (ts.isElementAccessExpression(node) && node.argumentExpression && ts.isStringLiteral(node.argumentExpression) && /^(style|cssText|insertRule|adoptedStyleSheets)$/.test(node.argumentExpression.text)) errors.push('DOM 样式注入');
    if (ts.isPropertyAccessExpression(node) && /^(style|cssText|insertRule|adoptedStyleSheets)$/.test(node.name.text)) errors.push('DOM 样式注入');
    if (ts.isIdentifier(node) && /^(makeStyles|makeResetStyles|mergeStyles|styled|css|createStyles)$/.test(node.text)) errors.push('CSS-in-JS');
    if (ts.isJsxAttribute(node) && /^(style|className|css|sx|dangerouslySetInnerHTML)$/.test(node.name.getText(ast))) errors.push('手写样式属性');
    if (ts.isJsxSpreadAttribute(node)) errors.push('不可审计的 JSX 属性展开');
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      if (/^(style|button|input|select|option|textarea|table|thead|tbody|tr|th|td|dialog|progress|meter|svg|canvas)$/.test(node.tagName.getText(ast))) errors.push('原生替代控件或样式');
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  if (name.endsWith('.html') && /<style\b|\bstyle\s*=|<link\b[^>]*(?:stylesheet|\.css)|<(?:button|input|select|textarea|table|dialog|svg|canvas)\b/i.test(source)) errors.push('HTML 样式或替代控件');
  return errors;
}

function scan(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    if (['node_modules', 'dist', '.git', 'scripts'].includes(entry.name)) return [];
    const path = resolve(dir, entry.name);
    if (entry.isDirectory()) return scan(path);
    if (!['.tsx', '.ts', '.jsx', '.js', '.mjs', '.cjs', '.html', '.css', '.scss', '.less', '.sass', '.styl'].includes(extname(path))) return [];
    if (/\.test\.|test-setup|vite.config/.test(path)) return [];
    return inspect(path, readFileSync(path, 'utf8')).map(error => `${path}: ${error}`);
  });
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const errors = scan(resolve('.'));
  if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1; }
  else console.log('Fluent-only / no-CSS 检查通过');
}