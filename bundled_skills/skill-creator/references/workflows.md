# Workflow Patterns

## Sequential Workflows

복잡한 작업은 명확한 순차 단계로 분해. SKILL.md 초반에 프로세스 개요를 제공하면 효과적:

```markdown
PDF 폼 작성 절차:

1. 폼 분석 (analyze_form.py 실행)
2. 필드 매핑 생성 (fields.json 편집)
3. 매핑 검증 (validate_fields.py 실행)
4. 폼 작성 (fill_form.py 실행)
5. 출력 검증 (verify_output.py 실행)
```

## Conditional Workflows

분기 로직이 있는 작업은 의사결정 지점을 안내:

```markdown
1. 수정 유형 결정:
   **새 콘텐츠 생성?** → 아래 "생성 워크플로우" 진행
   **기존 콘텐츠 편집?** → 아래 "편집 워크플로우" 진행

2. 생성 워크플로우: [단계들]
3. 편집 워크플로우: [단계들]
```
