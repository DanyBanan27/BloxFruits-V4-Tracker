# Digital signature (Windows)

The project includes `build_exe.bat` to build a standalone Windows EXE with the application icon, and `sign_release.ps1` to sign and verify that EXE.

**A trusted digital signature is not embedded in this source ZIP.** Signing requires the publisher's own code-signing certificate (usually a `.pfx`) and the Windows SDK `signtool.exe`. A self-signed certificate does not establish a verified public publisher and does not reliably prevent SmartScreen warnings.

1. Obtain a trusted code-signing certificate in the publisher's name and keep its private key/password private.
2. Run `build_exe.bat`.
3. In PowerShell, set the certificate path and (if needed) password for the current session:

   ```powershell
   $env:BFVT_SIGNING_PFX = "C:\path\to\publisher-certificate.pfx"
   $env:BFVT_SIGNING_PASSWORD = "your-certificate-password"
   .\sign_release.ps1
   ```

4. The script signs with SHA-256, requests a timestamp, and verifies the signature using SignTool.

Do not send anyone your PFX file or its password. A valid signature identifies the certificate publisher and helps verify file integrity, but it does not guarantee that SmartScreen will stop warning for a newly distributed file; reputation can take time to develop.
