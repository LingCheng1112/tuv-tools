Attribute VB_Name = "UnifyCheckboxes"

Sub ReplaceAllCheckboxes()
    Dim oldScreenUpdating As Boolean
    Dim errorNumber As Long
    Dim errorDescription As String
    
    On Error GoTo FatalError
    
    oldScreenUpdating = Application.ScreenUpdating
    Application.ScreenUpdating = False
    
    If ActiveDocument.ProtectionType <> wdNoProtection Then
        ActiveDocument.Unprotect
    End If
    
    ' Use temporary markers so text checkbox replacement does not conflict with checkbox controls.
    ReplacePlainText ChrW(&H2612), "@@CHECKED_BOX@@"
    ReplacePlainText ChrW(&H2610), "@@UNCHECKED_BOX@@"
    
    ReplaceLegacyCheckboxes
    
    ReplaceMarkerWithCheckbox "@@CHECKED_BOX@@", True
    ReplaceMarkerWithCheckbox "@@UNCHECKED_BOX@@", False

CleanExit:
    Application.ScreenUpdating = oldScreenUpdating
    
    If errorNumber <> 0 Then
        MsgBox "Replacement failed: " & errorNumber & " - " & errorDescription, vbExclamation
    End If
    Exit Sub

FatalError:
    errorNumber = Err.Number
    errorDescription = Err.Description
    Resume CleanExit
End Sub

Private Sub ReplaceLegacyCheckboxes()
    Dim i As Long
    Dim targetRange As Range
    Dim isChecked As Boolean
    Dim cc As ContentControl
    
    For i = ActiveDocument.FormFields.Count To 1 Step -1
        If ActiveDocument.FormFields(i).Type = wdFieldFormCheckBox Then
            Set targetRange = ActiveDocument.FormFields(i).Range.Duplicate
            isChecked = ActiveDocument.FormFields(i).CheckBox.Value
            
            ActiveDocument.FormFields(i).Delete
            Set cc = ActiveDocument.ContentControls.Add(wdContentControlCheckBox, targetRange)
            cc.Checked = isChecked
            NormalizeCheckboxFont cc
        End If
    Next i
End Sub

Private Sub ReplacePlainText(ByVal findText As String, ByVal replacementText As String)
    Dim rng As Range
    
    Set rng = ActiveDocument.Content
    With rng.Find
        .ClearFormatting
        .Replacement.ClearFormatting
        .Text = findText
        .Replacement.Text = replacementText
        .Forward = True
        .Wrap = wdFindStop
        .Format = False
        .Execute Replace:=wdReplaceAll
    End With
End Sub

Private Sub ReplaceMarkerWithCheckbox(ByVal markerText As String, ByVal isChecked As Boolean)
    Dim rng As Range
    Dim foundRange As Range
    Dim cc As ContentControl
    
    Set rng = ActiveDocument.Content
    With rng.Find
        .ClearFormatting
        .Text = markerText
        .Forward = True
        .Wrap = wdFindStop
        .Format = False
    End With
    
    Do While rng.Find.Execute
        Set foundRange = rng.Duplicate
        foundRange.Delete
        foundRange.Collapse wdCollapseStart
        
        On Error Resume Next
        Set cc = ActiveDocument.ContentControls.Add(wdContentControlCheckBox, foundRange)
        If Err.Number = 0 And Not cc Is Nothing Then
            cc.Checked = isChecked
            NormalizeCheckboxFont cc
            rng.SetRange Start:=cc.Range.End, End:=ActiveDocument.Content.End
        Else
            Err.Clear
            foundRange.Text = markerText
            rng.SetRange Start:=foundRange.End, End:=ActiveDocument.Content.End
        End If
        On Error GoTo 0
    Loop
End Sub

Private Sub NormalizeCheckboxFont(ByVal cc As ContentControl)
    cc.Range.Font.Italic = False
    cc.Range.Font.Bold = False
End Sub