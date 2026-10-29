targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name; used to derive resource names.')
param environmentName string

@description('Azure region for all resources. Pick one that offers your chosen model and Azure Speech.')
param location string

@description('Object ID of the signed-in user (azd sets AZURE_PRINCIPAL_ID). Gets the Foundry User role for local runs.')
param principalId string = ''

@description('Optional object ID of the service principal the robot signs in with. Gets the Foundry User role.')
param robotPrincipalId string = ''

@description('Chat model deployed for the agent (needs image input + tool calling).')
param chatModelName string = 'gpt-5.4-mini'

@description('Version of the chat model.')
param chatModelVersion string = '2026-03-17'

@description('Deployment name the app uses as FOUNDRY_MODEL.')
param chatDeploymentName string = chatModelName

@allowed(['GlobalStandard', 'DataZoneStandard', 'Standard'])
param chatSkuName string = 'GlobalStandard'

@description('Capacity in thousands of tokens per minute.')
param chatCapacity int = 50

var tags = { 'azd-env-name': environmentName, app: 'reachy-foundry' }
var token = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// Identities that use Foundry: the user for local runs, the robot's service principal.
var appPrincipals = concat(
  empty(principalId) ? [] : [{ id: principalId, type: 'User' }],
  empty(robotPrincipalId) ? [] : [{ id: robotPrincipalId, type: 'ServicePrincipal' }]
)

module foundry 'foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    tags: tags
    accountName: 'fdy-${take(replace(environmentName, '_', '-'), 20)}-${take(token, 6)}'
    projectName: 'reachy'
    deployments: [
      {
        name: chatDeploymentName
        modelName: chatModelName
        modelVersion: chatModelVersion
        skuName: chatSkuName
        capacity: chatCapacity
      }
    ]
    foundryUserPrincipals: appPrincipals
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_PROJECT_NAME string = foundry.outputs.projectName
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_MODEL string = chatDeploymentName
output AZURE_SPEECH_ENDPOINT string = foundry.outputs.speechEndpoint
