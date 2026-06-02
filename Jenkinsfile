// Declarative Jenkins pipeline.
// Designed for Jenkins 2.x with the AWS Credentials Plugin installed.
//
// Jenkins Credential IDs required (Manage Jenkins → Credentials):
//   aws-dev      → AWS credentials with deploy access to the dev account
//   aws-staging  → AWS credentials with deploy access to the staging account
//   aws-prod     → AWS credentials with deploy access to the prod account
//
// The pipeline is parameterised so any environment can be targeted manually.

pipeline {
    agent any

    parameters {
        choice(
            name: 'ENVIRONMENT',
            choices: ['dev', 'staging', 'prod'],
            description: 'Target deployment environment'
        )
    }

    environment {
        AWS_REGION  = 'us-east-1'
        IMAGE_TAG   = "${env.GIT_COMMIT}"
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Test') {
            steps {
                dir('backend') {
                    sh 'pip install -e ".[dev]"'
                    sh 'ruff check .'
                    sh 'pytest tests/ -q --cov=app --cov-report=xml'
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'backend/test-results/*.xml'
                }
            }
        }

        stage('Build & Push to ECR') {
            steps {
                withCredentials([[
                    $class:            'AmazonWebServicesCredentialsBinding',
                    credentialsId:     "aws-${params.ENVIRONMENT}",
                    accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                    secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                ]]) {
                    sh '''
                        chmod +x ./deploy/ecr-push.sh
                        ./deploy/ecr-push.sh "${ENVIRONMENT}" "${IMAGE_TAG}"
                    '''
                }
            }
        }

        // Production deployments require a manual approval step before proceeding.
        stage('Approval (prod only)') {
            when {
                expression { params.ENVIRONMENT == 'prod' }
            }
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: "Deploy image ${env.IMAGE_TAG} to PRODUCTION?",
                          ok: 'Deploy'
                }
            }
        }

        stage('Deploy to ECS') {
            steps {
                withCredentials([[
                    $class:            'AmazonWebServicesCredentialsBinding',
                    credentialsId:     "aws-${params.ENVIRONMENT}",
                    accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                    secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                ]]) {
                    sh '''
                        chmod +x ./deploy/ecs-deploy.sh
                        ./deploy/ecs-deploy.sh "${ENVIRONMENT}" "${IMAGE_TAG}"
                    '''
                }
            }
        }
    }

    post {
        success {
            echo "Deployed ${env.IMAGE_TAG} to ${params.ENVIRONMENT} successfully."
        }
        failure {
            echo "Deployment failed. Check the logs above."
        }
        always {
            cleanWs()
        }
    }
}
