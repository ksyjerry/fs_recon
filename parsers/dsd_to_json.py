import zipfile
from io import BytesIO
import os
import json
from bs4 import BeautifulSoup
from pathlib import Path
import sys

# [이전 helper 함수들은 동일하게 유지]
def assign_nested_value(data_dict, key_path, value):
    current = data_dict
    for i, key in enumerate(key_path):
        if i == len(key_path) - 1:
            current[key] = value
        else:
            if key not in current:
                current[key] = {}
            current = current[key]

def _parse_header_matrix(thead):
    rows = thead.find_all("tr", recursive=False)
    header_matrix = []
    for _ in rows:
        header_matrix.append([])

    for row_idx, tr in enumerate(rows):
        th_cells = tr.find_all("th", recursive=False)
        
        col_idx = 0
        while col_idx < len(header_matrix[row_idx]) and header_matrix[row_idx][col_idx] is not None:
            col_idx += 1

        for th in th_cells:
            rs = int(th.get("rowspan", "1"))
            cs = int(th.get("colspan", "1"))
            text = th.get_text(strip=True)

            needed_rows = row_idx + rs
            while len(header_matrix) < needed_rows:
                header_matrix.append([])

            while len(header_matrix[row_idx]) < col_idx + cs:
                header_matrix[row_idx].append(None)

            for r in range(row_idx, row_idx + rs):
                while len(header_matrix[r]) < col_idx + cs:
                    header_matrix[r].append(None)

            for rr in range(row_idx, row_idx + rs):
                for cc in range(col_idx, col_idx + cs):
                    header_matrix[rr][cc] = (text, rs, cs)

            col_idx += cs
            while col_idx < len(header_matrix[row_idx]) and header_matrix[row_idx][col_idx] is not None:
                col_idx += 1

    return header_matrix

def _build_header_paths(header_matrix):
    max_rows = len(header_matrix)
    if max_rows == 0:
        return []

    max_cols = max(len(row) for row in header_matrix)
    column_paths = [[] for _ in range(max_cols)]

    for r in range(max_rows):
        for c in range(max_cols):
            cell = header_matrix[r][c]
            if cell is None:
                continue
            text, rs, cs = cell
            if not column_paths[c] or column_paths[c][-1] != text:
                column_paths[c].append(text)

    return column_paths

def parse_multirow_table(table_tag):
    thead = table_tag.find("thead")
    tbody = table_tag.find("tbody")

    if not thead or not tbody:
        return []

    header_matrix = _parse_header_matrix(thead)
    column_paths = _build_header_paths(header_matrix)
    col_count = len(column_paths)

    result_list = []
    rows = tbody.find_all("tr", recursive=False)

    for row in rows:
        row_dict = {}
        td_cells = row.find_all("td", recursive=False)

        col_idx = 0
        for td in td_cells:
            text = td.get_text(strip=True)
            cs = int(td.get("colspan", "1"))

            for subcol in range(cs):
                if col_idx < col_count:
                    if subcol == 0:
                        assign_nested_value(row_dict, column_paths[col_idx], text)
                    else:
                        assign_nested_value(row_dict, column_paths[col_idx], "")
                    col_idx += 1

        result_list.append(row_dict)

    return result_list

def parse_singleheader_table(table_tag):
    thead = table_tag.find("thead")
    tbody = table_tag.find("tbody")

    if not thead or not tbody:
        return []

    header_cells = thead.find_all("th", recursive=True)
    headers = [cell.get_text(strip=True) for cell in header_cells]

    result = []
    rows = tbody.find_all("tr", recursive=False)
    for row in rows:
        row_dict = {}
        row_cells = row.find_all("td", recursive=True)
        
        col_idx = 0
        for cell in row_cells:
            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", "1"))
            
            for i in range(colspan):
                if col_idx < len(headers):
                    if i == 0:
                        row_dict[headers[col_idx]] = text
                    else:
                        row_dict[headers[col_idx]] = ""
                    col_idx += 1

        while col_idx < len(headers):
            row_dict[headers[col_idx]] = ""
            col_idx += 1

        result.append(row_dict)

    return result

def parse_table(table_tag):
    thead = table_tag.find("thead")
    if not thead:
        return []

    rows = thead.find_all("tr", recursive=False)
    if len(rows) <= 1:
        return parse_singleheader_table(table_tag)
    else:
        return parse_multirow_table(table_tag)

def xml_to_json(xml_content):
    soup = BeautifulSoup(xml_content, 'lxml')
    top_level_tags = soup.find_all(['p', 'table'], recursive=True)

    result_list = []
    for tag in top_level_tags:
        if tag.name == 'p':
            text_value = tag.get_text(strip=True)
            if text_value:
                result_list.append({"p": text_value})
        elif tag.name == 'table':
            table_value = parse_table(tag)
            if table_value:
                result_list.append({"table": table_value})

    return result_list

def process_dsd_to_json(dsd_path_str, output_json_str):
    """
    DSD 파일을 처리하여 JSON으로 변환합니다.
    
    Args:
        dsd_path_str (str): DSD 파일 경로 문자열
        output_json_str (str): 출력할 JSON 파일 경로 문자열
    """
    try:
        # 경로를 Path 객체로 변환
        dsd_path = Path(dsd_path_str).resolve()
        output_json = Path(output_json_str).resolve()
        
        print(f"DSD 파일 처리 시작: {dsd_path}")
        
        # 파일 존재 여부 확인
        if not dsd_path.exists():
            raise FileNotFoundError(f"DSD 파일을 찾을 수 없습니다: {dsd_path}")
        
        # 출력 디렉토리 생성
        output_json.parent.mkdir(parents=True, exist_ok=True)
        
        # DSD 파일 읽기
        with dsd_path.open('rb') as f:
            content = f.read()
        
        all_results = []
        
        # ZIP 파일로 처리
        with zipfile.ZipFile(BytesIO(content)) as zip_ref:
            # XML 파일만 처리
            xml_files = [f for f in zip_ref.filelist if f.filename.endswith('.xml')]
            
            if not xml_files:
                print("경고: DSD 파일 내에 XML 파일이 없습니다.")
                return
            
            for file_info in xml_files:
                print(f"XML 파일 처리 중: {file_info.filename}")
                
                # XML 파일 읽기
                try:
                    xml_content = zip_ref.read(file_info.filename).decode('utf-8')
                except UnicodeDecodeError:
                    print(f"경고: {file_info.filename} 파일의 인코딩을 UTF-8로 처리할 수 없습니다. euc-kr로 시도합니다.")
                    xml_content = zip_ref.read(file_info.filename).decode('euc-kr')
                
                # XML을 JSON으로 변환
                json_result = xml_to_json(xml_content)
                
                # 결과에 파일명과 함께 저장
                all_results.append({
                    "filename": file_info.filename,
                    "content": json_result
                })
        
        # 최종 JSON 저장
        with output_json.open('w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
            
        print(f"변환 완료: {output_json}")
        print(f"처리된 XML 파일 수: {len(xml_files)}")
        
    except Exception as e:
        print(f"오류 발생: {str(e)}", file=sys.stderr)
        raise

if __name__ == "__main__":
    # 명령줄 인자 처리
    if len(sys.argv) > 2:
        dsd_path = sys.argv[1]
        output_json = sys.argv[2]
    else:
        # 기본 파일 경로 설정
        dsd_path = r"DSD_GWSS.dsd"
        output_json = "result_new.json"
    
    # DSD를 JSON으로 변환
    process_dsd_to_json(dsd_path, output_json)