"""Answer-format diagnostics only; official correctness and termination remain separate."""
import re

def diagnose_answer_format(text):
    if '<final_answer>' not in text:
        return {'valid':False,'reason':'MISSING_FINAL_ANSWER_MARKER','choice':None}
    tail=text.rsplit('<final_answer>',1)[-1].replace('</final_answer>','').strip()
    match=re.fullmatch(r'\(([a-d])\)|([a-d])',tail,re.IGNORECASE)
    return {'valid':bool(match),'reason':'SINGLE_CHOICE' if match else 'NON_SINGLE_CHOICE_TAIL','choice':next((value.lower() for value in match.groups() if value),None) if match else None}

def official_parser_controls(grader):
    # Dummy labels only. Known upstream weaknesses are disclosed, never silently corrected.
    fixtures=[
        ('protocol-correct','<final_answer>(a)</final_answer>','(a)',True,True),
        ('protocol-wrong','<final_answer>(b)</final_answer>','(a)',False,True),
        ('protocol-ambiguous','<final_answer>(a) (b)</final_answer>','(a)',False,False),
        ('empty','','(a)',False,False),
        ('english-article-false-positive','Here is a cleaner implementation.\n```python\nreturn value\n```','(a)',True,False),
        ('ordinary-prose-false-positive','This is a careful explanation.','(a)',True,False),
        ('unmarked-single-choice','(a)','(a)',True,False),
        ('marker-with-extra-prose','<final_answer>(a) because this seems suitable.','(a)',True,False),
        ('protocol-plain-letter','<final_answer>a','(a)',True,True),
    ]
    cases=[]
    for name,text,label,expected,valid in fixtures:
        correct=bool(grader.extract_answer(text,label)[0]);diagnostic=diagnose_answer_format(text)
        assert correct==expected and diagnostic['valid']==valid,(name,correct,diagnostic)
        cases.append({'name':name,'dummyLabel':label,'officialCorrect':correct,'formatDiagnostic':diagnostic})
    return {'status':'KNOWN_OFFICIAL_FALLBACK_FALSE_POSITIVES_CONFIRMED','controls':cases,'officialMethodChanged':False,'textFallbackSafe':False,'requiresSeparateFormatReport':True,'realModelRequests':0,'realAnswerKeysRead':False}
